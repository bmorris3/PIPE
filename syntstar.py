# -*- coding: utf-8 -*-
"""
Created on Wed May 13 22:36:13 2020

@author: Alexis Brandeker, alexis@astro.su.se

Module with the star_bg class and methods to use the catalog file of background
stars (retrieved from Gaia) to produce synthetic images of the field of view
observed by CHEOPS, using an empirical PSF.
"""
import numpy as np
from astropy.io import fits

class star_bg():
    """Reads catalogue data on background stars and produces
    images of stars, to be removed from observations. Adjusts PSFs with
    rotational blurring and computes smearing trails.
    """
    def __init__(self, starcatfile, maxrad = None, shape=(200,200)):
        # CHEOPS pixel scale calibrated on HD80606 <-> HD80607 at (x,y)= (280,828)
        self.pxl_scl = 0.9969498004253621    # CHEOPS pixel scale, arcsec/pixel
        self.xpos, self.ypos, self.fscale, self.Teff = \
            self.read_starcat(starcatfile, maxrad)
        self.shape = shape
        self.catsize = len(self.fscale)


    def read_starcat(self, starcatfile, maxrad = None):
        """Reads star catalogue file as generated by the DRP.
        """
        with fits.open(starcatfile) as hdul:
            cat = hdul[1].data
            if maxrad is None:
                N = len(cat)
            else:
                N = np.searchsorted(cat['distance'], maxrad)
            
            fscale = 10**(-0.4*(cat['MAG_CHEOPS'][:N] - cat['MAG_CHEOPS'][0]))
            dx = ((cat['RA'][0]-cat['RA'][:N]) * 
                   np.cos(np.deg2rad(cat['DEC'][0])) * 3600.0 / self.pxl_scl)
            dy = ((cat['DEC'][:N]-cat['DEC'][0]) * 3600.0 / self.pxl_scl)
            Teff = cat['T_EFF'][:N]
            return dx, dy, fscale, Teff

        
    def rotate_cat(self, rolldeg):
        """Rotates the relative x and y positions of background
        stars according to submitted roll angle in degrees.
        """
        return rotate_position(self.xpos, self.ypos, rolldeg)

    
    def rotate_entry(self, entry, rolldeg):
        """Rotates the relative x and y positions for a single
        background star according to submitted roll angle in degrees.
        """
        return rotate_position(self.xpos[entry], self.ypos[entry], rolldeg)


    def brightest(self, radius):
        """Returns flux of brightest background star in radius, in
        units of target brightness
        """
        R2 = self.xpos[1:]**2 + self.ypos[1:]**2
        ind = R2 < radius**2
        if np.sum(ind) > 0:
            return np.max(self.fscale[1:][ind])
        return 0
            

    def image(self, x0, y0, rolldeg, psf_fun, shape=None,
              target=1, limflux=0, single_id=None, max_psf_rad=70):
        """Produces image with background stars at defined roll angle.
        target is how many entries should be skipped from the beginning
        of the catalogue. E.g., with target=1 the first entry is skipped, which
        is the target itself and not a background star. Similarly, for binaries
        set target=2 to skip the first 2 entries. limflux is at what fractional
        flux of the target background stars should be ignored. The signle_id is
        to select and draw an image of the selected star only.
        """        
        if shape == None:
            shape = self.shape
        dx, dy = self.rotate_cat(rolldeg)
        
        xcoo = np.arange(shape[1]) - x0
        ycoo = np.arange(shape[0]) - y0
        ret_img = np.zeros(shape)
        
        if single_id is None:
            id_range = range(target, self.catsize)
        else:
            id_range = [single_id]
        
        for n in id_range:
            # Skip faint stars
            if self.fscale[n] < limflux: continue
            
            if self.fscale[n] > 0.1: # Really bright
                psf_rad = min(70, max_psf_rad)
            elif self.fscale[n] > 1e-3: # Pretty bright
                psf_rad = min(50, max_psf_rad)
            else: # Not so bright
                psf_rad = min(30, max_psf_rad)
            i = int(x0 + dx[n])
            i0 = i - psf_rad
            # Skip stars further than PSF radius outside image
            if i0 >= shape[1]: continue
            i1 = i + psf_rad
            if i1 <= 0: continue
            i0 = max(i0, 0)
            i1 = min(i1, shape[1])
            j = int(y0 + dy[n])
            j0 = j - psf_rad
            if j0 >= shape[0]: continue
            j1 = j + psf_rad
            if j1 <= 0: continue
            j0 = max(j0, 0)
            j1 = min(j1, shape[0])
            ddx = xcoo[i0:i1] - dx[n]
            ddy = ycoo[j0:j1] - dy[n]
            psf_mat = psf_fun(ddy, ddx)
            if psf_mat.ndim == 1:
                psf_mat = np.reshape(psf_mat, (1, len(psf_mat)))            
            xmat,ymat = np.meshgrid(ddx,ddy)
            psf_mat[xmat**2+ymat**2 > psf_rad**2] = 0
            ret_img[j0:j1,i0:i1] += self.fscale[n] * psf_mat
        return ret_img

    
    def rotblur(self, x0, y0, rolldeg, blurdeg, psf_fun,
                oversample=1, shape=None, target=1, limflux=1e-3,
                single_id=None, max_psf_rad=70):
        """Returns an image (as defined by previous method) blurred
        by rotation. blurdeg is how many degrees the field rotates
        during exposure.
        """
        if shape == None:
            shape = self.shape
        resolution = np.rad2deg(1/np.max(shape))/oversample
        N = int(blurdeg / resolution) + 1
        rolldegs = rolldeg + 0.5 * blurdeg * np.linspace(-1, 1, N)
        ret_img = np.zeros(shape)
        for roll in rolldegs:
            ret_img += self.image(x0, y0, roll, psf_fun,
                                  shape=shape, target=target,
                                  limflux=limflux, single_id=single_id,
                                  max_psf_rad=max_psf_rad)/N
        return ret_img

    
    def smear(self, x0, y0, rolldeg, blurdeg, psf_fun, oversample=1,
              shape=None, limflux=1e-2, max_psf_rad=70):
        """Computes the smearing trail for all stars, including target.
        Returns a 1D array that can then be properly expanded to a 1D image.
        """
        if shape == None:
            shape = self.shape
        rb = self.rotblur(x0, y0, rolldeg, blurdeg, psf_fun,
                oversample, shape, target=0, limflux=limflux,
                max_psf_rad=max_psf_rad)
        return np.sum(rb, axis=0)


def rotate_position(x, y, rolldeg):
    """Function that rotates coordinates according to
    roll angle (in degrees)
    """
    rollrad = np.deg2rad(rolldeg)
    cosa = np.cos(rollrad)
    sina = np.sin(rollrad)
    xroll = x * cosa + y * sina
    yroll = -x * sina + y * cosa
    return xroll, yroll


def derotate_position(xroll, yroll, rolldegs):
    """Function that de-rotates coordinates according to
    roll angle (in degrees)
    """
    return rotate_position(xroll, yroll, -rolldegs)

    
    
        