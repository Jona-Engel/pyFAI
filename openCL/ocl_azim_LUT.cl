/*
 *   Project: Azimuthal regroupping OpenCL kernel for PyFAI.
 *            Kernel with full pixel-split using a LUT
 *
 *
 *   Copyright (C) 2012 European Synchrotron Radiation Facility
 *                           Grenoble, France
 *
 *   Principal authors: J. Kieffer (kieffer@esrf.fr)
 *   Last revision: 11/10/2012
 *
 *   This program is free software: you can redistribute it and/or modify
 *   it under the terms of the GNU Lesser General Public License as published
 *   by the Free Software Foundation, either version 3 of the License, or
 *   (at your option) any later version.
 *
 *   This program is distributed in the hope that it will be useful,
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *   GNU Lesser General Public License for more details.
 *
 *   You should have received a copy of the GNU General Public License
 *   and the GNU Lesser General Public License  along with this program.
 *   If not, see <http://www.gnu.org/licenses/>.
 */

/**
 * \file
 * \brief OpenCL kernels for 1D azimuthal integration
 */

//OpenCL extensions are silently defined by opencl compiler at compile-time:
#ifdef cl_amd_printf
  #pragma OPENCL EXTENSION cl_amd_printf : enable
  //#define printf(...)
#elif defined(cl_intel_printf)
  #pragma OPENCL EXTENSION cl_intel_printf : enable
#else
  #define printf(...)
#endif

#ifdef ENABLE_FP64
//	#pragma OPENCL EXTENSION cl_khr_fp64 : enable
	typedef double bigfloat_t;
#else
//	#pragma OPENCL EXTENSION cl_khr_fp64 : disable
	typedef float bigfloat_t;
#endif

#define GROUP_SIZE BLOCK_SIZE


/**
 * \brief Performs 1d azimuthal integration with full pixel splitting based on a LUT
 *
 * An image instensity value is spread across the bins according to the positions stored in the LUT.
 * The lut_index contains the positions of the pixel in the input array
 * Values of 0 in the mask are processed and values of 1 ignored as per PyFAI
 *
 * @param weights     Float pointer to global memory storing the input image.
 * @param bins        Unsigned int: number of output bins wanted (and pre-calculated)
 * @param lut_size    Unsigned int: dimension of the look-up table
 * @param lut_idx     Unsigned integers pointer to an array of with the index of input pixels
 * @param lut_coef    Float pointer to an array of coefficients for each input pixel
 * @param do_dummy    Bool/int: shall the dummy pixel be checked. Dummy pixel are pixels marked as bad and ignored
 * @param dummy       Float: value for bad pixels
 * @param delta_dummy Float: precision for bad pixel value
 * @param do_dark     Bool/int: shall dark-current correction be applied ?
 * @param dark        Float pointer to global memory storing the dark image.
 * @param do_flat     Bool/int: shall flat-field correction be applied ? (could contain polarization corrections)
 * @param flat        Float pointer to global memory storing the flat image.
 * @param outData     Float pointer to the output 1D array with the weighted histogram
 * @param outCount    Float pointer to the output 1D array with the unweighted histogram
 * @param outMerged   Float pointer to the output 1D array with the diffractogram

 */
__kernel void
lut_integrate(	const 	__global float 	*weights,
								 uint 	bins,
								 uint 	lut_size,
				const 	__global uint 	*lut_idx,
				const 	__global float 	*lut_coef,
								 int   	do_dummy,
								 float 	dummy,
								 float 	delta_dummy,
								 int 	do_dark,
				const 	__global float 	*dark,
								 int		do_flat,
				const 	__global 	float 	*flat,
						__global 	float	*outData,
						__global 	float	*outCount,
						__global 	float	*outMerge
		        )
{
	int idx, k, j, i= get_global_id(0);
	bigfloat_t sum_data = 0.0;
	bigfloat_t sum_count = 0.0;
	const bigfloat_t epsilon = 1e-10;
	float coef, data;
	if(i < bins)
	{
		for (j=0;j<lut_size;j++)
		{
			k = i*lut_size+j;
			idx = lut_idx[k];
			coef = lut_coef[k];
			if((idx <= 0) && (coef <= 0.0))
			  break;
			data = weights[idx];
			if( (!do_dummy) || (delta_dummy && (fabs(data-dummy) > delta_dummy))|| (data!=dummy) )
			{
				if(do_dark)
					data -= dark[idx];
				if(do_flat)
					data /= flat[idx];

				sum_data +=  coef * data;
				sum_count += coef;

			};//test dummy
		};//for j
		outData[i] = (float) sum_data;
		outCount[i] = (float) sum_count;
		if (sum_count > epsilon)
		  outMerge[i] = (float) sum_data / sum_count;
  };//if bins
};//end kernel

