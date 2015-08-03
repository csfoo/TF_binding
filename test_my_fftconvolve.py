import os, sys

import numpy as np
from scipy.signal import fftconvolve

from numpy.fft import rfft, irfft

USE_MY_FFT = False

def _next_regular(target):
    """
    Find the next regular number greater than or equal to target.
    Regular numbers are composites of the prime factors 2, 3, and 5.
    Also known as 5-smooth numbers or Hamming numbers, these are the optimal
    size for inputs to FFTPACK.
    Target must be a positive integer.
    """
    if target <= 6:
        return target

    # Quickly check if it's already a power of 2
    if not (target & (target-1)):
        return target

    match = float('inf')  # Anything found will be smaller
    p5 = 1
    while p5 < target:
        p35 = p5
        while p35 < target:
            # Ceiling integer division, avoiding conversion to float
            # (quotient = ceil(target / p35))
            quotient = -(-target // p35)

            # Quickly find next power of 2 >= quotient
            try:
                p2 = 2**((quotient - 1).bit_length())
            except AttributeError:
                # Fallback for Python <2.7
                p2 = 2**(len(bin(quotient - 1)) - 2)

            N = p2 * p35
            if N == target:
                return N
            elif N < match:
                match = N
            p35 *= 3
            if p35 == target:
                return p35
        if p35 < match:
            match = p35
        p5 *= 5
        if p5 == target:
            return p5
    if p5 < match:
        match = p5
    return match

def my_convolve(in1, in2):
    shape = len(in1) + len(in2) - 1
    fshape = _next_regular(shape)
    ret = irfft(rfft(in1, fshape) *
                rfft(in2, fshape), fshape)
    return ret[:shape]

def multi_convolve(signals):
    res = signals[0]
    for signal in signals[1:]:
        res = fftconvolve(res, signal)
    return res

def my_multi_convolve(signals):
    shape = sum(len(x)-1 for x in signals) + 1
    fshape = _next_regular(shape)
    res = rfft(signals[0], fshape)
    for signal in signals[1:]:
        res *= rfft(signal, fshape)
    ret = irfft(res, fshape)
    return ret[:shape]

def t1():
    xs = []
    for i in xrange(50):
        x = np.arange(1000, dtype=float)
        x = x/x.sum()
        xs.append(x)

    for j in xrange(30):
        if USE_MY_FFT:
            my_multi_convolve(xs)
        else:
            multi_convolve(xs)
    return

def main():
    ## timing
    t1()
    return
    x = np.arange(10, dtype=float)
    x = x/x.sum()
    xnew = np.arange(10, dtype=float)
    xnew = xnew/xnew.sum()
    print np.convolve(x, xnew)
    print fftconvolve(x, xnew)
    print my_convolve(x, xnew)
    pass


main()
