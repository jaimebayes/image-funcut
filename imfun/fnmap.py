import numpy as np
import time, sys
#from imfun.aux_utils import ifnot
from swan import pycwt

import itertools as itt

## def ifnot(a, b):
##     "if a is not None, return a, else return b"
##     if a == None: return b
##     else: return a

from imfun import lib, ui
ifnot = lib.ifnot

def isseq(obj):
    return hasattr(obj, '__iter__')


def cwt_iter(fseq,
             frange,
             nfreqs = 128,
             wavelet = pycwt.Morlet(),
             normL = None,
             max_pixels = None,
             verbose = True,
             **kwargs):
    """
    Iterate over cwt of the time series for each pixel
    *fseq* -- frame sequence
    *frange* -- frequency range or vector of frequencies
    *wavelet* -- wavelet object (default pycwt.Morlet())
    *normL* -- length of normalizing part (baseline) of the time series

    """
    tick = time.clock()
    L = fseq.length()
    subframe = kwargs.has_key('sliceobj') and kwargs['sliceobj'] or None
    shape = fseq.shape(subframe)
    npix = shape[0]*shape[1]
    normL = ifnot(normL, L)
    pixel_iter = fseq.pix_iter(**kwargs)
    max_pixels = ifnot(max_pixels, npix)

    if len(frange) == 2:  # a low-high pair
        freqs = np.linspace(frange[0], frange[1], num=nfreqs)
    else:
        freqs= np.array(frange.copy())
    nfreqs = len(freqs)

    pixel_counter = 0
    npix = min(npix, max_pixels)
    cwtf = pycwt.cwt_f
    for s,i,j in pixel_iter:
        s = (s-np.mean(s[:normL]))/np.std(s[:normL])
        eds = pycwt.eds(cwtf(s, freqs, 1./fseq.dt, wavelet, 'zpd'))
        pixel_counter+= 1
        if verbose:
            sys.stderr.write("\rpixel %05d of %05d"%(pixel_counter,npix))
        yield eds, i, j
        if pixel_counter > max_pixels:
            break
    if verbose:
        sys.stderr.write("\n Finished in %3.2f s\n"%(time.clock()-tick))

def cwtmap(fseq,
           tranges,
           frange,
           func = np.mean,
           **kwargs):
    """
    Wavelet-based 'functional' map of the frame sequence
    
    Arguments
    ----------
    *fseq* -- frame sequence
    *tranges* -- list of time ranges
    *frange* -- frequency range or vector of frequencies
    *func* -- function to apply to the wavelet spectrogram within the window
              of interest. Default, np.mean
    **kwargs -- to be passed to cwt_iter
    """
    subframe = kwargs.has_key('sliceobj') and kwargs['sliceobj'] or None
    shape = fseq.shape(subframe)

    tstarts = map(lambda x: int(x[0]/fseq.dt), tranges)
    tstops = map(lambda x: int(x[1]/fseq.dt), tranges)

    out = np.ones((len(tranges),)+shape, np.float64)
    for eds,i,j in cwt_iter(fseq,frange,**kwargs):
        for tk, tr in enumerate(tranges):
            out[tk,i,j] = func(eds[:,tstarts[tk]:tstops[tk]])
    return out

def loc_max_pos(v):
    return [i for i in xrange(1,len(v)-1)
            if (v[i] > v[i-1]) and (v[i] > v[i+1])]

def cwt_freqmap(fseq,
                tranges,
                frange,
                nfreqs = 32,
                **kwargs):
    if len(frange) > 2:
        freqs = frange
    else:
        freqs = np.linspace(frange[0], frange[-1],nfreqs)
    def _dominant_freq(arr):
        ma = np.mean(arr,1) 
        if np.max(ma) < 1e-7:
            print "mean wavelet power %e too low"%np.mean(ma)
            return -1.0
        x = loc_max_pos(ma)
        if x:
            xma = ma[x]
            xma1 = (xma>=np.max(xma)).nonzero()[0]
            n = x[xma1]
        else:
            print "No local maxima. This shouldn't have happened!"
            x = (ma>=np.max(ma)).nonzero()[0]
            try: n = x[0]
            except:
                n = 0
                print x,ma
        return freqs[n]
    return cwtmap(fseq,tranges,freqs,func=_dominant_freq,**kwargs)


def avg_eds(fseq, *args, **kwargs):
    cwit = cwt_iter(fseq, *args, **kwargs)
    out,i,j = cwit.next()
    counter = 1.0
    for eds, i, j in cwit:
        out += eds
        counter += 1
    return out/counter

def _feature_map(fseq, rhythm, freqs, **kwargs):
    from scipy.interpolate import splrep,splev
    subframe = kwargs.has_key('sliceobj') and kwargs['sliceobj'] or None
    shape = fseq.shape(subframe)

    L = fseq.length()
    tinds = np.arange(L)
    tck = splrep(rhythm[:,0], rhythm[:,1])
    rhfreqs = map(int, np.round(splev(tinds, tck)))
    rhsd = 6

    out = np.ones((L,)+shape, np.float64)
    for eds,i,j in cwt_iter(fseq,freqs,**kwargs):
        for k in tinds:
            fi1, fi2  = rhfreqs[k] - rhsd, rhfreqs[k] + rhsd
            out[k,i,j] = np.sum(eds[fi1:fi2,k])
        #out[:,i,j] /= eds.mean()

    return out

def tanh_step(start,stop):
    "To be used for correlation"
    def _(t):
        v =  0.5*(1 + np.tanh(10*(t-start)) * np.tanh(-10*(t-stop)))
        return v - np.mean(v)
    return _

def MH_onoff(start,stop):
    "To be used for correlation"
    mh = pycwt.Mexican_hat()
    w = stop-start
    scale = 2*w*mh.fc
    def _(t):
        v = mh.psi((t - (start+0.5*w))/scale)
        return v
    return _

## def norm1(v, L):
##     return (v - np.mean(v[:L]))/np.std(v[:L])

DFoSD = lib.DFoSD # Normalization function

def detrend(y, ord=2, take=None):
    x = np.arange(len(y))
    if take is None:
        take = x
    p = np.polyfit(x[take],y[take],ord)
    return y - np.polyval(p, x)


def meanactmap(fseq, (start,stop), normL=None):
    L = fseq.length()
    normL = ifnot(normL, L)
    out = np.zeros(fseq.shape())
    tv = fseq.timevec()
    mrange = (tv > start)*(tv < stop)
    for s,j,k in fseq.pix_iter():
        sx = detrend(s,take=range(330))
        out[j,k] = np.mean(DFoSD(s,normL)[mrange])
    return out
    

def corrmap(fseq, (start, stop), normL=None, sigfunc = tanh_step):
    L = fseq.length()
    normL = ifnot(normL, L)
    out = np.zeros(fseq.shape())
    comp_sig = sigfunc(start, stop)(fseq.timevec())
    for s,j,k in fseq.pix_iter():
        out[j,k] = np.correlate(DFoSD(s,normL), comp_sig, 'valid')[0]
    return out

def fftmap(fseq, frange, func=np.mean,
           normL = None,
           verbose = True,
           **kwargs):
        """
        Fourier-based functional mapping
        frange : a range of frequencies in Hz, e.g. (1.0, 1.5)
        kern  : a kernel to convolve each frame with
        func  : range reducing function. np.mean by default, may be np.sum as well
        """
        tick = time.clock()
        L = fseq.length()
        shape = fseq.shape(kwargs.has_key('sliceobj') and
                           kwargs['sliceobj'] or None)
        total = shape[0]*shape[1]
        out = np.ones(shape, np.float64)
        k = 0
        freqs = np.fft.fftfreq(L, fseq.dt)
        pix_iter = fseq.pix_iter(**kwargs)
        normL = ifnot(normL, L)
        fstart,fstop = frange
        fmask = (freqs >= fstart)*(freqs < fstop)
        for s,i,j in pix_iter:
            s = s-np.mean(s[:normL])
            s_hat = np.fft.fft(s)
            x = (abs(s_hat)/np.std(s[:normL]))**2
            out[i,j] = func(x[fmask])
            k+=1
            if verbose:
                sys.stderr.write("\rpixel %05d of %05d"%(k,total))
        if verbose:
            sys.stderr.write("\n Finished in %3.2f s\n"%(time.clock()-tick))
        return out

            

    
