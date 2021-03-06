import numpy as np
import arextract
import arflux
import arload
import armasters
import armbase
import armsgs
import arproc
import ararc
import arsave
import arspecobj
import artrace
import arqa

try:
    from xastropy.xutils.xdebug import set_trace
#    from xastropy.xutils import xdebug as xdb
except ImportError:
    from pdb import set_trace

# Logging
msgs = armsgs.get_logger()

def ARMLSD(argflag, spect, fitsdict, reuseMaster=False):
    """
    Automatic Reduction and Modeling of Long Slit Data

    Parameters
    ----------
    argflag : dict
      Arguments and flags used for reduction
    spect : dict
      Properties of the spectrograph.
    fitsdict : dict
      Contains relevant information from fits header files
    reuseMaster : bool
      If True, a master frame that will be used for another science frame
      will not be regenerated after it is first made.
      This setting comes with a price, and if a large number of science frames are
      being generated, it may be more efficient to simply regenerate the master
      calibrations on the fly.

    Returns
    -------
    status : int
      Status of the reduction procedure
      0 = Successful execution
      1 = ...
    """
    status = 0

    # Create a list of science exposure classes
    sciexp = armbase.SetupScience(argflag, spect, fitsdict)
    numsci = len(sciexp)

    # Create a list of master calibration frames
    masters = armasters.MasterFrames(spect['mosaic']['ndet'])

    # Start reducing the data
    for sc in range(numsci):
        slf = sciexp[sc]
        scidx = slf._idx_sci[0]
        msgs.info("Reducing file {0:s}, target {1:s}".format(fitsdict['filename'][scidx], slf._target_name))
        # Loop on Detectors
        for kk in xrange(slf._spect['mosaic']['ndet']):
            det = kk + 1  # Detectors indexed from 1
            ###############
            # Get amplifier sections
            fitsdict = arproc.get_ampsec_trimmed(slf, fitsdict, det, scidx)
            ###############
            # Generate master bias frame
            update = slf.MasterBias(fitsdict, det)
            if update and reuseMaster:
                armbase.UpdateMasters(sciexp, sc, det, ftype="bias")
            ###############
            # Generate a bad pixel mask (should not repeat)
            update = slf.BadPixelMask(det)
            if update and reuseMaster:
                armbase.UpdateMasters(sciexp, sc, det, ftype="arc")
            ###############
            # Estimate gain and readout noise for the amplifiers
            msgs.work("Estimate Gain and Readout noise from the raw frames...")
            ###############
            # Generate a master arc frame
            update = slf.MasterArc(fitsdict, det)
            if update and reuseMaster:
                armbase.UpdateMasters(sciexp, sc, det, ftype="arc")
            ###############
            # Determine the dispersion direction (and transpose if necessary)
            slf.GetDispersionDirection(fitsdict, det, scidx)
            if slf._bpix[det-1] is None:
                slf.SetFrame(slf._bpix, np.zeros((slf._nspec[det-1], slf._nspat[det-1])), det)
            ###############
            # Generate a master trace frame
            update = slf.MasterTrace(fitsdict, det)
            if update and reuseMaster:
                armbase.UpdateMasters(sciexp, sc, det, ftype="flat", chktype="trace")
            ###############
            # Generate an array that provides the physical pixel locations on the detector
            slf.GetPixelLocations(det)
            ###############
            # Determine the edges of the spectrum (spatial)
            lordloc, rordloc, extord = artrace.trace_orders(slf, slf._mstrace[det-1], det, singleSlit=True, pcadesc="PCA trace of the slit edges")
            slf.SetFrame(slf._lordloc, lordloc, det)
            slf.SetFrame(slf._rordloc, rordloc, det)

            # Convert physical trace into a pixel trace
            msgs.info("Converting physical trace locations to nearest pixel")
            pixcen = artrace.phys_to_pix(0.5*(slf._lordloc[det-1]+slf._rordloc[det-1]), slf._pixlocn[det-1], 1)
            pixwid = (slf._rordloc[det-1]-slf._lordloc[det-1]).mean(0).astype(np.int)
            lordpix = artrace.phys_to_pix(slf._lordloc[det-1], slf._pixlocn[det-1], 1)
            rordpix = artrace.phys_to_pix(slf._rordloc[det-1], slf._pixlocn[det-1], 1)
            slf.SetFrame(slf._pixcen, pixcen, det)
            slf.SetFrame(slf._pixwid, pixwid, det)
            slf.SetFrame(slf._lordpix, lordpix, det)
            slf.SetFrame(slf._rordpix, rordpix, det)
            # Save QA for slit traces
            arqa.slit_trace_qa(slf, slf._mstrace[det-1], slf._lordpix[det-1], slf._rordpix[det-1], extord, desc="Trace of the slit edges")

            ###############
            # Prepare the pixel flat field frame
            update = slf.MasterFlatField(fitsdict, det)
            if update and reuseMaster: armbase.UpdateMasters(sciexp, sc, det, ftype="flat", chktype="pixflat")
            ###############
            # Derive the spectral tilt
            if slf._tilts[det-1] is None:
                # First time tilts are derived for this arc frame --> derive the order tilts
                tilts = None
                nitertilts = 2
                doQA = False
                for tt in range(nitertilts):
                    msgs.info("Iterating on spectral tilts -- Iteration {0:d}/{1:d}".format(tt+1, nitertilts))
                    if tt == nitertilts-1:
                        doQA = True
                    tilts, satmask = artrace.model_tilt(slf, det, slf._msarc[det-1], guesstilts=tilts, plotQA=doQA)
                slf.SetFrame(slf._tilts, tilts, det)
                slf.SetFrame(slf._satmask, tilts, det)

                # Setup arc parameters (e.g. linelist)
                arcparam = ararc.setup_param(slf, sc, det, fitsdict)
                slf.SetFrame(slf._arcparam, arcparam, det)
                ###############
                # Extract arc and identify lines
                wv_calib = ararc.simple_calib(slf, det)
                slf.SetFrame(slf._wvcalib, wv_calib, det)

                ###############
                # Generate a master wave frame
                update = slf.MasterWave(fitsdict, det)
                if update and reuseMaster:
                    armbase.UpdateMasters(sciexp, sc, det, ftype="arc", chktype="wave")


            ###############
            # Check if the user only wants to prepare the calibrations
            msgs.info("All calibration frames have been prepared")
            if slf._argflag['run']['preponly']:
                msgs.info("If you would like to continue with the reduction,"
                          +msgs.newline()+"disable the run+preponly command")
                continue
            ###############
            # Standard star (is this a calibration, e.g. goes above?)
            msgs.info("Processing standard star")
            msgs.warn("Assuming one star per detector mosaic")
            update = slf.MasterStandard(scidx, fitsdict)
            if update and reuseMaster:
                armbase.UpdateMasters(sciexp, sc, det, ftype="standard")

            ###############
            # Load the science frame and from this generate a Poisson error frame
            msgs.info("Loading science frame")
            sciframe = arload.load_frames(slf, fitsdict, [scidx], det,
                                          frametype='science',
                                          msbias=slf._msbias[det-1],
                                          transpose=slf._transpose)
            sciframe = sciframe[:, :, 0]
            # Extract
            msgs.info("Processing science frame")
            arproc.reduce_frame(slf, sciframe, scidx, fitsdict, det)


            #continue
            #msgs.error("UP TO HERE")
            ###############
            # Perform a velocity correction
            if (slf._argflag['reduce']['heliocorr'] == True) & False:
                if slf._argflag['science']['load']['extracted'] == True:
                    msgs.warn("Heliocentric correction will not be applied if an extracted science frame exists, and is used")
                msgs.work("Perform a full barycentric correction")
                msgs.work("Include the facility to correct for gravitational redshifts and time delays (see Pulsar timing work)")
                msgs.info("Performing a heliocentric correction")
                # Load the header for the science frame
                slf._waveids = arvcorr.helio_corr(slf, scidx[0])
            else:
                msgs.info("A heliocentric correction will not be performed")

            ###############
            # Using model sky, calculate a flexure correction
            msgs.warn("Implement flexure correction!!")

            ###############
            # Flux
            msgs.work("Need to check for existing sensfunc")
            msgs.work("Consider using archived sensitivity if not found")
            msgs.info("Fluxing with {:s}".format(slf._sensfunc['std']['name']))
            arflux.apply_sensfunc(slf, scidx, fitsdict)

        # Write
        arsave.save_1d_spectra(slf)
        # Close the QA for this object
        slf._qa.close()
        # Free up some memory by replacing the reduced ScienceExposure class
        sciexp[sc] = None
    return status


def instconfig(slf, det, scidx, fitsdict):
    """ Returns a unique config string for the current slf

    Parameters
    ----------
    scidx: int
       Exposure index (max=9999)
    """
    from collections import OrderedDict
    config_dict = OrderedDict()
    config_dict['S'] = 'slitwid'
    config_dict['D'] = 'dichroic'
    config_dict['G'] = 'disperser'
    config_dict['T'] = 'cdangle'
    #
    config = ''
    for key in config_dict.keys():
        try:
            comp = str(fitsdict[config_dict[key]][scidx])
        except KeyError:
            comp = '0'
        #
        val = ''
        for s in comp:
            if s.isdigit():
                val = val + s
        config = config + key+'{:s}-'.format(val)
    # Binning
    try:
        binning = slf._spect['det'][det-1]['binning']
    except KeyError:
        msgs.warn("Assuming 1x1 binning for your detector")
        binning = '1x1'
    val = ''
    for s in binning:
        if s.isdigit():
            val = val + s
    config = config + 'B{:s}'.format(val)
    # Return
    return config

    """
    msgs.warn("Flat indexing needs to be improved in arsort.setup")
    fidx = slf._name_flat.index(slf._mspixflat_name)
    if fidx > 9:
        msgs.error("Not ready for that many flats!")
    aidx = slf._name_flat.index(slf._mspixflat_name)
    setup = 10*(aidx+1) + fidx
    return setup
    """
