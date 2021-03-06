# This is a comment line

# Change the default settings
run ncpus 1
run spectrograph lris_blue
out verbose 2
out overwrite True
out sorted lris_blue_long_600_4000_d560.xml

# Reduce
reduce usebias bias      # How to subtract the detector bias (bias, overscan, dark, none), you can also specify a master calibrations file if it exists.
#trace disp direction 0   # Manually specify the dispersion direction (0 for row, 1 for column)

# Read in the data
data read
 /Users/xavier/PYPIT/LRIS_blue/TST_RAW/b150910_*.fits.gz
data end

spect read
 fits calwin 12.
 pixflat number 1
 bias number 3
 arc number 1
 trace number 1
 set bias     b150910_2036.fits.gz  
 set bias     b150910_2037.fits.gz 
 set bias     b150910_2038.fits.gz 
 set pixflat  b150910_2051.fits.gz 
 set trace    b150910_2051.fits.gz 
 set standard b150910_2083.fits.gz
spect end
