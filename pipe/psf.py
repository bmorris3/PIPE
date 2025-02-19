#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Mar  6 14:26:19 2020

@author: Alexis Brandeker, alexis@astro.su.se

Worker functions for multi_psf. Fit known PSFs to data.
"""

import numpy as np
from numpy.linalg import lstsq
from scipy.optimize import nnls
from pipe.reduce import coo_mat
from .spline_pca import psf_integral

def fit(psf_list, frame, noise, mask, xc, yc, 
                radius=50, krn_scl=0.3,
                krn_rad=3, bg_fit=0):
    """Fit multiple PSF PCs simultaneousy to single frame. Fits
    for motion blur.
    Returns: 
        Fitted PSF sampled on frame pixels
        Determined background (single value)
        Motion blur matrix
        Scale factor data/PSF (proportional to flux)
        Arrray of PSF PC coefficients
    """
    xmat, ymat = coo_mat(frame.shape, xc, yc)
    xcoo =  np.arange(frame.shape[0]) - xc
    ycoo =  np.arange(frame.shape[1]) - yc

    aperture = xmat**2 + ymat**2 <= radius**2
    aperture *= mask
    fvec = frame[aperture]
    nvec = noise[aperture]
    Npix = len(fvec)
    
    xkern = np.linspace(-krn_scl * krn_rad, krn_scl * krn_rad,
                        2 * krn_rad + 1)
    xkmat, ykmat = np.meshgrid(xkern, xkern)
    xk = xkmat.flatten()
    yk = ykmat.flatten()
    Nk = len(xk)
    Npsf = len(psf_list)
    
    if bg_fit ==0:
        psfs = np.zeros((Npix, Nk+1))
        psfs[:,Nk] = 1/nvec     # background
    else:
        psfs = np.zeros((Npix, Nk))
    psf_norms = psf_integral(psf_list)

    # First, derive offset matrix using only the first 
    # PSF

    for n in range(Nk):
        psf = psf_list[0](ycoo-yk[n], xcoo-xk[n])
        psfs[:,n] = psf[aperture]/nvec

    kvec = _least_square(psfs, fvec/nvec)
         
    # Use derived offset matrix to fit PSF list

    if bg_fit==0:
        psfs = np.zeros((Npix, Npsf+1))
        psfs[:, Npsf] = 1/nvec     # background
    else:
        psfs = np.zeros((Npix, Npsf))
    
    for m in range(Npsf):
        psf = np.zeros(frame.shape)
        for n in range(Nk):
            psf += kvec[n]*psf_list[m](ycoo-yk[n], xcoo-xk[n])
        psfs[:,m] = psf[aperture]/nvec
                       
    w = _least_square(psfs, fvec/nvec)
 
    psf = np.zeros(aperture.shape)
    for m in range(Npsf):
        for n in range(Nk):
            psf += w[m]*kvec[n]*psf_list[m](ycoo-yk[n], xcoo-xk[n]) 

    if bg_fit==0:
        bg = w[-1]
        last_w = len(w)-1
        last_k = len(kvec)-1
    else:
        bg = 0
        last_w = len(w)
        last_k = len(kvec)
        
    kmat = np.reshape(kvec[:Nk], (len(xkern),len(xkern)))
    wsum = np.sum(psf_norms*w[:last_w])
    
    if np.isnan(wsum):
        print('Warning: wsum == NaN encountered')
        wsum = 1
    elif wsum == 0:
        print('Warning: wsum == 0 encountered')
        wsum = 1

    return psf, bg, kmat, np.sum(kvec[:last_k])*wsum, w[:last_w]/wsum
    

def fit_binary(psf_list0, psf_list1, frame, noise, mask, xc0, yc0, xc1, yc1,
                psfrad=70, fitrad=30, krn_scl=0.3, krn_rad=3):
    """Fit multiple PSF PCs simultaneousy for binary in single frame. Fits
    for PCs motion blur independently for the two components. PSF libraries
    are defined for each component.
    Returns: 
        Fitted PSF to component 0 sampled on frame pixels
        Fitted PSF to component 1 sampled on frame pixels
        Determined background (single value)
        Motion blur matrix for component 0
        Motion blur matrix for component 1
        Scale factor data/PSF (proportional to flux) for component 0
        Scale factor data/PSF (proportional to flux) for component 1
        Arrray of PSF PC coefficients of component 0
        Arrray of PSF PC coefficients of component 1
    """
    
    xmat0, ymat0 = coo_mat(frame.shape, xc0, yc0)
    xcoo0 =  np.arange(frame.shape[0]) - xc0
    ycoo0 =  np.arange(frame.shape[1]) - yc0
    xmat1, ymat1 = coo_mat(frame.shape, xc1, yc1)
    xcoo1 =  np.arange(frame.shape[0]) - xc1
    ycoo1 =  np.arange(frame.shape[1]) - yc1

    notsel0 = xmat0**2+ymat0**2 > fitrad**2
    notsel1 = xmat1**2+ymat1**2 > fitrad**2
    apt0 = xmat0**2+ymat0**2 < psfrad**2
    apt1 = xmat1**2+ymat1**2 < psfrad**2
    aperture = (notsel0*notsel1 == 0)
    
    if mask is not None:
        aperture *= mask
        
    fvec = frame[aperture]
    nvec = noise[aperture]
    Npix = len(fvec)
    
    # Make offset grid
    xkern = np.linspace(-krn_scl * krn_rad, krn_scl * krn_rad,
                        2 * krn_rad + 1)
    xkmat, ykmat = np.meshgrid(xkern, xkern)
    xk = xkmat.flatten()
    yk = ykmat.flatten()
    Nk = len(xk)
    Npsf = len(psf_list0)
    
    # First iteration: find offset coefficients
    # assuming average PSF
    # Independent coefficients for PSF0 and PSF1
    
    psfs = np.zeros((Npix, 2*Nk+1))
    psfs[:, 2*Nk] = 1/nvec     # background

    for n in range(Nk):
        psf0 = psf_list0[0](ycoo0-yk[n], xcoo0-xk[n])*apt0
        psf1 = psf_list1[0](ycoo1-yk[n], xcoo1-xk[n])*apt1
        psfs[:, n] = psf0[aperture]/nvec
        psfs[:, n+Nk] = psf1[aperture]/nvec

    kvec = _least_square(psfs, fvec/nvec)

    bg = kvec[-1]
    psfs = np.zeros((Npix, 2*Npsf+1))
    psfs[:, 2*Npsf] = 1/nvec     # background
    
    # Compute best composite PSFs using derived
    # offset coefficients (independent for PSF0 and PSF1)
    
    for m in range(Npsf):
        psf0 = np.zeros(frame.shape)
        psf1 = np.zeros(frame.shape)
        for n in range(Nk):
            psf0 += kvec[n]*psf_list0[m](ycoo0-yk[n], xcoo0-xk[n])*apt0
            psf1 += kvec[n+Nk]*psf_list1[m](ycoo1-yk[n], xcoo1-xk[n])*apt1
        psfs[:, m] = psf0[aperture]/nvec    
        psfs[:, m+Npsf] = psf1[aperture]/nvec    
    
    w = _least_square(psfs, fvec/nvec)
    
    # Second iteration: find new offset coefficients
    # using derived PSF

    psfs = np.zeros((Npix, 2*Nk+1))
    psfs[:, 2*Nk] = 1/nvec     # background

    for n in range(Nk):
        psf0 = np.zeros(frame.shape)
        psf1 = np.zeros(frame.shape)
        for m in range(Npsf):
            psf0 += w[m]*psf_list0[m](ycoo0-yk[n], xcoo0-xk[n])*apt0
            psf1 += w[m+Npsf]*psf_list1[m](ycoo1-yk[n], xcoo1-xk[n])*apt1
        psfs[:, n] = psf0[aperture]/nvec
        psfs[:, n+Nk] = psf1[aperture]/nvec

    kvec = _least_square(psfs, fvec/nvec)
    bg = kvec[-1]
    
    psf0 = np.zeros(frame.shape)
    psf1 = np.zeros(frame.shape)
    for m in range(Npsf):
        for n in range(Nk):
            psf0 += kvec[n]*w[m]*psf_list0[m](ycoo0-yk[n], xcoo0-xk[n])*apt0
            psf1 += kvec[n+Nk]*w[m+Npsf]*psf_list1[m](ycoo1-yk[n], xcoo1-xk[n])*apt1

    kmat0 = np.reshape(kvec[:Nk], (len(xkern),len(xkern)))
    kmat1 = np.reshape(kvec[Nk:(2*Nk)], (len(xkern),len(xkern)))
    psf_norms0 = psf_integral(psf_list0)
    psf_norms1 = psf_integral(psf_list1)
    wsum0 = np.sum(psf_norms0*w[:Npsf])
    wsum1 = np.sum(psf_norms1*w[Npsf:-1])

    return (psf0, psf1, bg, kmat0, kmat1, np.sum(kvec[:Nk])*wsum0, 
            np.sum(kvec[Nk:(2*Nk)])*wsum1, w[:Npsf]/wsum0, w[Npsf:-1]/wsum1)


def _least_square(eq_mat, res_vec, non_negative=False):
    """Help function that derives least square coefficients for
    linear combination of vectors in eq_mat matrix that best match
    the result vector res_vec. If non_negative true, a non-negative
    least squares method is used instead.
    """
    if non_negative:
        return nnls(eq_mat, res_vec)[0]
    
    # Bug in lstsq causes it to sometimes fail on first call
    # I *think* this is corrected in most recent versions of numpy
    try: 
        return lstsq(eq_mat, res_vec, rcond=None)[0]
    except:
        return lstsq(eq_mat, res_vec, rcond=None)[0]
    