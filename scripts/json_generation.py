import nibabel as nb
import numpy as np
import json
import csv
import os
import glob
import subprocess
from nilearn import plotting as nip
from nilearn import image
from argparse import ArgumentParser


def get_centers(brain):
    """
    Get coordinate centers given a nifti image loaded with nibabel
    
    Returns a dictionary of label: coordinate as an [x, y, z] array
    """
    dat = brain.get_data()
    #nip.find_parcellation_cut_coords(dat, label_hemisphere='left')
    #nip.find_parcellation_cut_coords(dat, label_hemisphere='right')
    
    labs, size = np.unique(dat, return_counts=True)
    #labs = labs[labs != 0]
    # Line below throwing memory error. I will likely calculate each layer one at a time
    # and find the center
    fd_dat = np.stack([np.asarray(dat == lab).astype('float64') for lab in labs], axis=3)
    parcels = nb.Nifti1Image(dataobj=fd_dat, header=brain.header, affine=brain.affine)
    regions_imgs = image.iter_img(parcels)
    # compute the centers of mass for each ROI
    coords_connectome = [nip.find_xyz_cut_coords(img) for img in regions_imgs]
    return dict(zip(labs, coords_connectome)), size

def main():

    parser = ArgumentParser(
        description="Script to take already MNI-aligned atlas images and generate json file information."
    )
    parser.add_argument(
        "input_file",
        help="""The path of the mri parcellation
        file you intend to process.""",
        action="store",
    )
    parser.add_argument(
        "output_dir",
        help="""The directory to store the generated nii.gz and/or json file(s).""",
        action="store",
    )
    parser.add_argument(
        "--output_name",
        help="""Name assigned to both the processed parcellation file and its corresponding,
        json label file. Do not include the file type (nii.gz, nii, or json).
        If None, 'input_file' and 'reference_brain' names will be combined to
        make <input_file>_<ref_brain>.nii.gz/.json. Default is None.""",
        action="store",
        default=None,
    )
    parser.add_argument(
        "--voxel_size",
        help="""Whether you want to resample the input parcellation to a specific voxel size,
        this process will be done before alignment to a reference brain. Enter either '1', '2',
        or '4' to resample to 1x1x1mm, 2x2x2mm, and 4x4x4mm, respectfully. Default is None""",
        action="store",
        default=None,
    )
    parser.add_argument(
        "--ref_brain",
        help="""Path for reference image you wish to register your parcellation too,
        for the best results have its voxel size match --voxel_size. If None, registration
        to reference brain will not be done. Default is None.""",
        action="store",
        default=None,
    )

    parser.add_argument(
        "--label_csv",
        help="csv file containing the ROI label information for the parcellation file, default is None",
        action="store",
        default=None,
    )


    # and ... begin!
    print("\nBeginning neuroparc ...")

    # ---------------- Parse CLI arguments ---------------- #
    result = parser.parse_args()
    input_file = result.input_file
    output_dir = result.output_dir
    output_name = result.output_name
    vox_size = result.voxel_size
    ref_brain = result.ref_brain
    csv_f = result.label_csv


    if not output_name:
        inp = input_file.split("/")[-1]
        inp = inp.split(".nii")[0]
        refp = ref_brain.split("/")[-1]
        refp = refp.split(".nii")[0]
        output_name = f"{inp}_{refp}"

    # Load and organize csv for use in json creation
    if csv_f:
        biglist=[]
        with open(csv_f, newline='') as csvfile:
            spamreader = csv.reader(csvfile, delimiter=',')
            for row in spamreader:
                biglist.append(row[0])
                biglist.append(row[1])
            csv_dict = {biglist[i]: biglist[i+1] for i in range(0, len(biglist), 2)}

    
    if vox_size:
        # align input file to the dataset grid of "master"
        cmd = f"3dresample -input {input_file} -prefix {output_dir}/{output_name}.nii.gz -master {ref_brain}"
        subprocess.call(cmd, shell=True)
        # Change datatype of resampled file to 768?
        im = nb.load(f"{output_dir}/{output_name}.nii.gz")
        newdat = im.get_data().astype(np.uint32)
        im.header['datatype'] = 768
        nb.save(nb.Nifti1Image(dataobj=newdat, header=im.header, affine=im.affine), filename=f"{output_dir}/{output_name}.nii.gz")


    if ref_brain:
        output_reg = f"{output_dir}/reg_{output_name}.nii.gz"
        # register image to atlas
        cmd = f"flirt -in {output_dir}/{output_name}.nii.gz -out {output_reg} -ref {ref_brain} -applyisoxfm {vox_size} -interp nearestneighbour"
        subprocess.call(cmd, shell=True)
        
        # Change datatype of registered file to 768?
        im = nb.load(f"{output_reg}")
        newdat=im.get_data().astype(np.uint32)
        im.header['datatype'] = 768
        nb.save(nb.Nifti1Image(dataobj=newdat, header=im.header, affine=im.affine), filename=output_reg)

    
    jsout = f"{output_dir}/reg_{output_name}.json"
    js_contents={}
        
    parcel_im = nb.load(output_reg)
    parcel_centers, size = get_centers(parcel_im)
    if csv_f:
    # find a corresponding json file
        js_contents[str(0)] = {"label": "empty", "center":None}
        for (k, v) in csv_dict.items():
            k=int(k)
            try:
                js_contents[str(k)] = {"label": v, "center": parcel_centers[int(k)]}
            except KeyError:
                js_contents[str(k)] = {"label": v, "center": None}
        #Atlas-wide Metadata
        js_contents["MetaData"] = {"AtlasName": '', "Description": '',
        "Native Coordinate Space": '', "Hierarchical": '', "Symmetrical": '',
        "Number of Regions":'', "Average Volume Per Region":'', "Year Generated":'',
        "Generation Method":'', "Source":''}

        with open(jsout, 'w') as jso:
            json.dump(js_contents, jso, indent=4)
            
    else:
        js_contents[str(0)] = {"label": "empty", "center":None}
        for (k, v) in parcel_centers.items():
            k=int(k)
            try:
                js_contents[str(k)] = {"label": None,"center": parcel_centers[int(k)],"size":int(size[int(k)])}
            except KeyError:
                js_contents[str(k)] = {"label": None, "center": None}
        
        #Atlas-wide Metadata
        js_contents["MetaData"] = {"AtlasName": '', "Description": '',
        "Native Coordinate Space": '', "Hierarchical": '', "Symmetrical": '',
        "Number of Regions":'', "Average Volume Per Region":'', "Year Generated":'',
        "Generation Method":'', "Source":''}
                
        with open(jsout, 'w') as jso:
            json.dump(js_contents, jso, indent=4)
            


if __name__ == "__main__":
    main()