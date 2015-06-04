import numpy as np
import healpy as hp
from scipy.optimize import curve_fit
import matplotlib.pylab as plt
from lsst.sims.skybrightness import twilightFunc
import lsst.sims.skybrightness as sb
import os
import lsst.sims.photUtils.Bandpass as Bandpass

def lineCurve(xdata, x0,x1):
    mag = x0*xdata+x1
    return mag

def expPlusC(xdata, x0,x1, x3):
    """
    Let the sky flux be exponentially declining and hit some constant value
    """
    flux = x0*np.exp( (xdata)*x1)+x3
    return flux

# Make a function that fits everything simultaneously.  Prob need a pixel-by-pixel additive constant, and mag.  Maybe slope depends only on az?

def variableBack(xdata, *args):
    """
    function to fit a single decay slope and a variable background at each helpixel.

    xdata should have keys:
    sunAlt
    hpid

    args:
    0: slope
    1:hpid: magnitudes
    hpid+1:2*hpid: constant offsets
    """
    args = np.array(args)
    hpmax = np.max(xdata['hpid'])
    result = args[xdata['hpid']+1]*np.exp( xdata['sunAlt'] * args[0]) + args[xdata['hpid']+2+hpmax]
    return result


# Let's just fit a slope and intercept for all the healpixels

filters = ['R','G','B']
#filters = ['G']
brightLimits = {'R':5., 'G':5., 'B':5.}
#faintLimits = {'R':8., 'G':7.5, 'B':8.}
counter = 1
colors = ['r','g','b']
fig = plt.figure()
sunAltMax = np.radians(-11.)
residPlot1 = plt.figure()
residPlot2 = plt.figure()
paramList = []

fitDict = {}




canonDict = {}
canonFiles = {'R':'red_canon.csv','G':'green_canon.csv','B':'blue_canon.csv'}
path = os.path.join(os.environ.get('SIMS_SKYBRIGHTNESS_DATA_DIR'), 'Canon')
for key in canonFiles.keys():
    data = np.loadtxt(os.path.join(path,canonFiles[key]), delimiter=',',
                      dtype=zip(['wave','throughput'],[float,float]))
    band = Bandpass()
    band.setBandpass(data['wave'], data['throughput'])
    canonDict[key]=band


for filterName in filters:
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

    xdata = np.zeros(magMaps.shape, dtype=zip(['sunAlt','hpid', 'alt', 'az'],[float,int,float,float]))

    xdata['hpid'] = hpid.reshape(hpid.size,1) #hpid[:,np.newaxis].T  #np.tile(hpid,72).reshape(768,72)
    #xdata['hpid'] = xdata['hpid'].T
    xdata['alt'] = alt.reshape(alt.size,1)
    xdata['az'] = az.reshape(az.size,1)

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

    p0 = [50.]
    # Have a parameter for each pixel flux at sunAlt = 0
    p0.extend([40.]* np.size(np.unique(xdata['hpid'])))
    # Have a parameter for each pixel constant level-off value (sunAlt --> -20 degrees)
    p0.extend([1e-4]* np.size(np.unique(xdata['hpid'])))
    p0 = np.array(p0)

    fitParams, fitCovariances = curve_fit(variableBack, xdata,flux,sigma=fluxerr,  p0=p0)

    ax = fig.add_subplot(3,1,counter)
    ax.semilogy(xdata['sunAlt'], flux, 'ko', alpha=.1)
    ax.plot(xdata['sunAlt'], variableBack(xdata,*fitParams), color=colors[counter-1], alpha=.2)
    np.savez('slopeFits_%s.npz'%colors[counter-1], fitParams=fitParams, hpidIn=hpidIn)

    modelFluxes = variableBack(xdata,*fitParams)
    modelMags = -2.5*np.log10(modelFluxes)
    trueMags = -2.5*np.log10(flux)
    resids = modelMags-trueMags

    fig2 = plt.figure(num=10)
    fluxMap = np.zeros(npix)+hp.UNSEEN
    magMap = fluxMap.copy()
    fluxMap[hpidIn] = fitParams[1:np.size(np.unique(xdata['hpid']))+1]
    magMap[hpidIn] = -2.5*np.log10(fitParams[1:np.size(np.unique(xdata['hpid']))+1])
    constMap = np.zeros(npix)+hp.UNSEEN
    constMap[hpidIn] = fitParams[np.size(np.unique(xdata['hpid']))+1:]
    mask = np.where(fluxMap == hp.UNSEEN)
    unmask = np.where(fluxMap != hp.UNSEEN)
    magMap[unmask] = magMap[unmask]-magMap[unmask].max()
    #magMap[mask] = hp.UNSEEN
    hp.mollview(magMap, fig=10, unit='mag/sq arcsec', rot=(0,90),
                title='Canon %s, sunAlt=0'%colors[counter-1])
    fig2.savefig('Plots/magMap_%s.png'%colors[counter-1])
    plt.close(fig2)

    # Let's print out a little info:
    print '-------'
    print colors[counter-1]
    print 'airmass,  az,  mag - max(mag)'
    good = np.where(magMap[unmask] == magMap[unmask].max())
    for ind in good[0]:
        print '%.2f,  %.2f,  %.2f' % (airmass[ind], np.degrees(az[ind]), magMap[unmask][ind])
    good = np.where( (airmass[unmask] == airmass[unmask].max()) & (az[unmask] == az[unmask].min()) )
    ind = good[0]
    print '%.2f,  %.2f,  %.2f' % (airmass[ind], np.degrees(az[ind]), magMap[unmask][ind])
    good = np.where( (airmass[unmask] == airmass[unmask].max()) & (az[unmask] == np.pi/2.) )
    ind = good[0]
    print '%.2f,  %.2f,  %.2f' % (airmass[ind], np.degrees(az[ind]), magMap[unmask][ind])
    good = np.where( (airmass[unmask] == airmass[unmask].max()) & (az[unmask] == np.pi) )
    ind = good[0]
    print '%.2f,  %.2f,  %.2f' % (airmass[ind], np.degrees(az[ind]), magMap[unmask][ind])



    # OK, now let's try the better fitter
    p0 = np.zeros(5.+np.size(np.unique(xdata['hpid'])))
    p0[0] = fitParams[0]
    p0[1] = -20.
    p0[2:5] = -1.
    p0[5:] += fitParams[-np.size(np.unique(xdata['hpid'])):]

    xdata2 = np.zeros(xdata.size, dtype=zip(['sunAlt','hpid','airmass','azRelSun'],[float,int,float,float]))
    xdata2['sunAlt'] = xdata['sunAlt']
    xdata2['hpid'] = xdata['hpid']
    xdata2['azRelSun'] = xdata['az']
    xdata2['airmass'] =  1./np.cos(np.pi/2.-xdata['alt'])

    fitParams2, fitCov2 = curve_fit(twilightFunc, xdata2, flux, sigma=fluxerr,
                                    p0=p0)

    fitDict[filterName] = fitParams2[0:5]

    paramList.append(fitParams2)
    modelFluxes2 = twilightFunc(xdata2, *fitParams2)
    modelMags2 = -2.5*np.log10(modelFluxes2)
    resids2 = modelMags2-trueMags

    constMap2 = np.zeros(npix)+hp.UNSEEN
    constMap2[hpidIn] = fitParams2[5:]

    ax = residPlot1.add_subplot(3,1,counter)
    s = ax.scatter(np.degrees(xdata['sunAlt']), resids, c=np.degrees(xdata['alt']), alpha=.2, edgecolor=None)
    ax.set_xlabel('Sun Altitude (degrees)')
    ax.set_ylabel('Model - Data (mags)')
    ax.set_title('Az-dependent fits, RMS=%.2f, %s'%(resids.std(), filterName))
    cb = residPlot1.colorbar(s)
    cb.set_label('Target Altitude (degrees)')

    ax = residPlot2.add_subplot(3,1,counter)
    s = ax.scatter(np.degrees(xdata['sunAlt']), resids2, c=np.degrees(xdata['alt']), alpha=.2, edgecolor=None)
    ax.set_xlabel('Sun Altitude (degrees)')
    ax.set_ylabel('Model - Data (mags)')
    ax.set_title('Az-independent fits, RMS=%.2f, %s'%(resids2.std(), filterName))
    cb = residPlot2.colorbar(s)
    cb.set_label('Target Altitude (degrees)')


    #--------
    # Let's look at the zeropoints
    hpids = np.unique(xdata2['hpid'])
    flux_constants = fitParams2[5:] # this is the constant value
    constMap = np.zeros(npix, dtype=float) + hp.UNSEEN
    constMap[hpids] = flux_constants

    # Maybe mask out the direction of the sun?
    esoAlt = alt[hpids]
    esoAz = az[hpids]
    sm = sb.SkyModel(twilight=False, moon=False, zodiacal=False)
    sm.setRaDecMjd(esoAz,esoAlt, 4000, azAlt=True)
    sm.computeSpec()
    esoMags = sm.computeMags(canonDict[filterName])

    good = np.where( (esoAz > np.pi/2) & (esoAz < 3.*np.pi/2 ) )
    m0 = np.median(esoMags[good]+2.5*np.log10(constMap[hpids][good]))


    # Let's apply the median zeropoint to the fits
    fitDict[filterName][1] = fitDict[filterName][1]/(10.**(0.4*m0))


    counter += 1


print '-------------'
print 'Best fit parameters:'
print fitDict

fig.savefig('simulfits.png')
plt.close(fig)
residPlot1.tight_layout()
residPlot1.savefig('Plots/residPlot1.png')
plt.close(residPlot1)

residPlot2.tight_layout()
residPlot2.savefig('Plots/residPlot2.png')
plt.close(residPlot2)

#hp.mollview(constMap2, rot=(0,90))

i=300
# Spot check a few model fits to see how the function looks
np.where(xdata2['sunAlt'] == xdata2['sunAlt'][i])

modelMap = np.zeros(npix) + hp.UNSEEN
dataMap = np.zeros(npix) + hp.UNSEEN
good = np.where(xdata2['sunAlt'] == xdata2['sunAlt'][i])
modelMap[xdata2['hpid'][good]] = modelFluxes2[good]
dataMap[xdata2['hpid'][good]] = flux[good]

#hp.mollview(modelMap, rot=(0,90))
#hp.mollview(dataMap, rot=(0,90))
magResid = -2.5*np.log10(modelMap/dataMap)
masked = np.where(modelMap == hp.UNSEEN)
unmasked = np.where(modelMap != hp.UNSEEN)
magResid[masked] = hp.UNSEEN
hp.mollview(magResid, rot=(0,90))