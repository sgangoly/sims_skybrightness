import numpy as np
import healpy as hp
from scipy.optimize import curve_fit
import matplotlib.pylab as plt
#from lsst.sims.skybrightness import twilightFunc
import lsst.sims.skybrightness as sb
import os
import lsst.sims.photUtils.Bandpass as Bandpass

# Load up the twilight sky maps generated by buildTwilMaps.py and fit a function to them






def twilightFunc(xdata, *args):
    """
    xdata: numpy array with columns 'alt', 'az', 'sunAlt' all in radians.
    az should be relative to the sun (i.e., sun is at az zero.

    based on what I've seen, here's my guess for how to fit the twilight:
    args[0] = ratio of (zenith twilight flux at sunAlt = -12) and dark sky zenith flux
    args[1] = decay slope for all pixels (mags/radian)
    args[2] = airmass term for hemisphere away from the sun. (factor to multiply max brightness at zenith by)
    args[3] = az term for hemisphere towards sun
    args[4] = zenith dark sky flux
    args[5:] = zenith dark sky times constant (optionall)

    """

    ## XXX--I think I might want to promote this to a free parameter to fit.
    amCut = 1.1

    args = np.array(args)
    az = xdata['azRelSun']
    airmass = xdata['airmass']
    sunAlt = xdata['sunAlt']
    flux = np.zeros(az.size, dtype=float)
    away = np.where( (airmass <= amCut) | ((az >= np.pi/2) & (az <= 3.*np.pi/2)))
    towards = np.where( (airmass > amCut) & ((az < np.pi/2) | (az > 3.*np.pi/2)))


    flux = args[0]*args[4]*10.**(args[1]*(sunAlt+np.radians(12.))+args[2]*(airmass-1.))
    flux[towards] *= 10.**(args[3]*np.cos(az[towards])*(airmass[towards]-1.))

    # Adding in an X^2 term seems to help, but now I might just be fitting the zodiacal light?
    # But maybe the zodical is getting mostly absobed in the constant term.

    flux[towards] *= 10.**(args[5]*np.cos(az[towards])*(airmass[towards]-1.)**2 )
    # Adding cos^2 term didn't do much
    #flux[towards] *= 10.**(args[5]*np.cos(az[towards])**2.*(airmass[towards]-1.) )

    # This let's one fit the dark sky background simultaneously.
    # It assumes the dark sky is a function of airmass only. Forced to be args[4] at zenith.
    if np.size(args) >=6:
        #flux += args[4]*np.exp( args[5]*(airmass-1.))
        # Formulate it this way so that it's like adding a constant magnitude
        flux[away] += args[4]*np.exp( args[6:][xdata['hpid'][away]]*(airmass[away]-1.))
        flux[towards] += args[4]*np.exp(args[6:][xdata['hpid'][towards]]*(airmass[towards]-1.))

    return flux


# Set up the Canon filters
filters = ['R','G','B']
#filters = ['G']
brightLimits = {'R':5., 'G':5., 'B':5.}
#faintLimits = {'R':8., 'G':7.5, 'B':8.}
sunAltMax = np.radians(-11.)

colors = ['r','g','b']

canonDict = {}
canonFiles = {'R':'red_canon.csv','G':'green_canon.csv','B':'blue_canon.csv'}
path = os.path.join(os.environ.get('SIMS_SKYBRIGHTNESS_DATA_DIR'), 'Canon')
for key in canonFiles.keys():
    data = np.loadtxt(os.path.join(path,canonFiles[key]), delimiter=',',
                      dtype=zip(['wave','throughput'],[float,float]))
    band = Bandpass()
    band.setBandpass(data['wave'], data['throughput'])
    canonDict[key]=band

# XXX
filters = ['R']
for filterName in filters:
    # Load the twilght map
    twi = np.load('TwilightMaps/twiMaps_'+filterName+'.npz')
    # set the surface brightness limits to try and fit.
    brightLimit = brightLimits[filterName]
    #faintLimit = faintLimits[filterName]

    sunAlts = twi['sunAlts'].copy()
    magMaps = twi['magMap'].copy()
    rmsMaps = twi['rmsMap'].copy()

    nside = hp.npix2nside(magMaps[:,0].size)
    npix = magMaps[:,0].size
    hpid = np.arange(magMaps[:,0].size)

    lat, az = hp.pix2ang(nside, np.arange(npix))
    alt = np.pi/2.-lat
    airmass = 1./np.cos(np.pi/2.-alt)

    lam = np.where((airmass < 2.5) & (airmass >=1))
    bam = np.where( (airmass > 2.5) | (airmass <1))

    xdata = np.zeros(magMaps.shape, dtype=zip(['sunAlt','hpid', 'airmass', 'azRelSun'],[float,int,float,float]))

    xdata['hpid'] = hpid.reshape(hpid.size,1) #hpid[:,np.newaxis].T  #np.tile(hpid,72).reshape(768,72)
    #xdata['hpid'] = xdata['hpid'].T
    xdata['airmass'] =  1./np.cos(np.pi/2.-alt.reshape(alt.size,1))
    #xdata['alt'] = alt.reshape(alt.size,1)
    xdata['azRelSun'] = az.reshape(az.size,1)

    xdata['sunAlt'] = sunAlts

    ydata = magMaps.copy()
    err = rmsMaps.copy()

    # Mask out any high airmass, or no data, or no error.
    mask = np.ones(ydata.shape)
    amv = np.ones(airmass.size)
    amv[bam] = 0
    mask = mask*amv.reshape(amv.size,1)
    # Mask nans, where there's no error estimate, and bright pixels
    mask[np.isnan(ydata)] = 0
    mask[np.where(err == 0)] = 0
    mask[np.where(ydata < brightLimit)] = 0

    # mask out high sun altitudes
    mask[np.where(xdata['sunAlt'] > sunAltMax)] = 0

    collapse = np.sum(mask, axis=1)

    notnulls = np.where(collapse != 0)
    xdata = xdata[notnulls,:]
    ydata = ydata[notnulls, :]
    err = err[notnulls,:]
    mask = mask[notnulls,:]
    good = np.where(mask == 1)
    hpidIn = hpid[notnulls].copy()

    xdata = xdata[good].ravel()
    ydata = ydata[good].ravel()
    err = err[good].ravel()

    flux = 10.**(-0.4*ydata)
    fluxerr = 10.**(-0.4*(ydata)) - 10.**(-0.4*(ydata+err ))
    trueMags = -2.5*np.log10(flux)

    p0=[2.,20., 0.3, 0.3, 3.0e-4, .3, .1]

    # Need to also fit and remove the dark sky component
    constants = np.zeros(npix)+.05
    p0.extend(constants)
    p0 = np.array(p0)

    fitParams, fitCov = curve_fit(twilightFunc, xdata,flux,sigma=fluxerr, p0=p0)

    modelFluxes = twilightFunc(xdata, *fitParams)
    modelMags = -2.5*np.log10(modelFluxes)
    resids = modelMags-trueMags


    # Right--I have that bright spot that I think might actually be zodiacal light.  May want to try masking that for now.

    nmaps = 9.
    uAlt = np.unique(xdata['sunAlt'])
    indices = np.arange(0,uAlt.size,np.ceil(uAlt.size/nmaps) )

    for i,indx in enumerate(indices):
        residMap = np.zeros(npix, dtype=float)+hp.UNSEEN
        good = np.where(xdata['sunAlt'] == uAlt[indx])
        residMap[xdata['hpid'][good]] = resids[good]
        hp.mollview(residMap, rot=(0,90), fig=5, sub=(3,3,i+1),
                    title='sunAlt = %.2f' % np.degrees(uAlt[indx]),
                    max=0.2,min=-0.2)

    plt.show()

    plt.figure()
    plt.scatter(np.degrees(xdata['sunAlt']), resids, c=xdata['airmass'], alpha=.1)
    plt.title('rms = %f' % resids.std())
