# LaMAR Usage Guide

Complete guide for using LaMAR to generate 3D meshes from NavVis data and localize phone images.

---

## Table of Contents

1. [Docker Setup](#docker-setup)
2. [Mesh Generation Pipeline](#mesh-generation-pipeline)
3. [Single Image Localization](#single-image-localization)
4. [Understanding the Pipeline](#understanding-the-pipeline)
5. [Output Format](#output-format)
6. [Troubleshooting](#troubleshooting)

---

## Docker Setup

### Build the LaMAR Docker Image

```bash
cd /path/to/lamar-benchmark
docker build --target lamar -t lamar:lamar -f Dockerfile ./
```

### Environment Variables

**For local machine:**
```bash
export NAVVIS_DATA=/home/rohamzn/ETH_Uni/Mixed_Reality/CNSG/mesh_pipeline/data
export REPO=/home/rohamzn/ETH_Uni/Mixed_Reality/lamar-benchmark
```

**For edna server:**
```bash
export NAVVIS_DATA=/home/rzendehdel/work/CNSG/mesh_pipeline/data
export REPO=/home/rzendehdel/work/CNSG/mesh_pipeline/third_party/lamar-benchmark
```

---

## Mesh Generation Pipeline

**Purpose:** Generate combined 3D meshes from multiple NavVis sessions.

### Setup Docker Run Command

```bash
export DOCKER_RUN="docker run -it --rm --init \
    --shm-size=2g \
    -v ${REPO}:${REPO} \
    -v ${NAVVIS_DATA}:${NAVVIS_DATA} \
    -w ${REPO} \
    lamar:lamar"
```

### Run the Pipeline

```bash
$DOCKER_RUN python -m pipelines.pipeline_scans \
    --capture_path ${NAVVIS_DATA} \
    --input_path ${NAVVIS_DATA}/sessions \
    --sessions navvis_2021-05-10_19.34.30 navvis_2022-02-06_12.55.11 navvis_2022-02-26_16.21.10
```

**What this does:**
- Processes multiple NavVis sessions
- Combines them into a unified mesh
- Outputs a merged 3D reconstruction

---

## Single Image Localization

Localize a single phone image against your NavVis map data.

**Important:** The predicted pose will be in **NavVis world coordinates**, directly usable with your `pointcloud.ply` and meshes.

### Quick Start (Recommended)

#### Setup Environment Variables

```bash
export NAVVIS_DATA=/path/to/your/navvis/data
export REPO=/path/to/lamar-benchmark
export QUERY_IMAGE=/path/to/your/query/image.jpg
```

**Example:**
```bash
export NAVVIS_DATA=/home/rohamzn/ETH_Uni/Mixed_Reality/CNSG/mesh_pipeline/data
export REPO=/home/rohamzn/ETH_Uni/Mixed_Reality/lamar-benchmark
export QUERY_IMAGE=/home/rohamzn/ETH_Uni/Mixed_Reality/lamar-data/test1.jpg
```

#### Run Localization (Docker)

```bash
docker run -it --rm --init \
    --shm-size=2g \
    -v ${REPO}:${REPO} \
    -v ${NAVVIS_DATA}:${NAVVIS_DATA} \
    -v $(dirname ${QUERY_IMAGE}):$(dirname ${QUERY_IMAGE}) \
    -w ${REPO} \
    lamar:lamar \
    python localize_single_image.py \
        --map_path ${NAVVIS_DATA}/navvis_2022-02-06_12.55.11 \
        --query_image ${QUERY_IMAGE} \
        --output_dir ./outputs
```

#### Run Localization (Local)

```bash
python localize_single_image.py \
    --map_path ~/ETH_Uni/Mixed_Reality/CNSG/mesh_pipeline/data/navvis_2022-02-06_12.55.11 \
    --query_image /path/to/your/photo.jpg \
    --output_dir ./outputs
```

### Manual Setup with lamar.run

If you prefer more control over the process:

**Step 1:** Create the directory structure:

```bash
mkdir -p my_localization/sessions/query_phone/raw_data/images
```

**Step 2:** Link your NavVis map:

```bash
ln -s ~/ETH_Uni/Mixed_Reality/CNSG/mesh_pipeline/data/navvis_2022-02-06_12.55.11 \
      my_localization/sessions/map
```

**Step 3:** Copy your query image:

```bash
cp /path/to/your/photo.jpg my_localization/sessions/query_phone/raw_data/images/query.jpg
```

**Step 4:** Create metadata files:

**`my_localization/sessions/query_phone/sensors.txt`:**
```
# sensor_id, name, sensor_type, [sensor_params]+
camera, Phone camera, camera, PINHOLE, 4032, 3024, 2822, 2822, 2016, 1512
```
*Adjust width, height, focal length, and principal point (cx, cy) for your camera*

**`my_localization/sessions/query_phone/images.txt`:**
```
# timestamp, sensor_id, image_path
1000000, camera, images/query.jpg
```

**`my_localization/sessions/query_phone/queries.txt`:**
```
1000000, camera
```

**Step 5:** Run localization:

```bash
python -m lamar.run \
    --scene my_localization \
    --captures ./ \
    --outputs ./outputs \
    --ref_id map \
    --query_id query_phone \
    --retrieval netvlad \
    --feature superpoint \
    --matcher superglue
```

**Note:** We use `--retrieval netvlad` instead of `fusion` to avoid PyTorch 2.6 compatibility issues with AP-GeM.

---

## Understanding the Pipeline

### What Happens During Localization

The pipeline runs these steps:

1. **Extract features from map** - SuperPoint features from all NavVis images (~30 min first time, cached after)
2. **Select image pairs** - Using NetVLAD retrieval to find similar images
3. **Match features** - SuperGlue matches between map image pairs (~2-4 hours first time, cached after)
4. **Build 3D map** - Triangulate matched points (preserving NavVis coordinates)
5. **Extract query features** - SuperPoint features from your phone image (fast)
6. **Retrieve candidates** - Find similar map images to your query (fast)
7. **Match query to map** - SuperGlue matches between query and map (fast)
8. **Estimate pose** - PnP (Perspective-n-Point) algorithm (fast)

**Important:** Steps 1-3 only run once and are cached. Subsequent localizations are much faster (~1-2 minutes).

### Core Scripts

- **`python -m lamar.run`** - Main localization pipeline ([lamar/run.py](lamar/run.py))
- **`localize_single_image.py`** - Simplified script for single image localization
- **`scantools/run_phone_to_capture.py`** - Converts phone recordings to Capture format
- **`lamar/tasks/feature_extraction.py`** - Extracts SuperPoint/R2D2 features
- **`lamar/tasks/pair_selection.py`** - Image retrieval (NetVLAD, overlap-based)
- **`lamar/tasks/feature_matching.py`** - SuperGlue/LightGlue matching
- **`lamar/tasks/mapping.py`** - Triangulation and 3D reconstruction
- **`lamar/tasks/pose_estimation.py`** - PnP pose estimation

## Output Format

### Success Output

```
📸 Candidate map images matched against query:
  Found 10 candidate images:
    1. map/raw_data/images_undistr_center/camera_0/frame_00123.jpg
    2. map/raw_data/images_undistr_center/camera_0/frame_00124.jpg
    ...

✓ Successfully localized!
  Position: [x, y, z]  # in meters, NavVis coordinates
  Rotation (quaternion): [qw, qx, qy, qz]  # camera orientation

Pose saved to: outputs/.../poses.txt
```

### Pose File Format

**`poses.txt`:**
```
# timestamp, sensor_id, qw, qx, qy, qz, tx, ty, tz
1000000, camera, 0.707, 0.0, 0.707, 0.0, 10.5, 2.3, -5.1
```

Where:
- `qw, qx, qy, qz` - Rotation quaternion (camera to world)
- `tx, ty, tz` - Translation vector (camera position in world coordinates)

### Output Files

- `outputs/.../poses.txt` - Camera pose (position + quaternion rotation)
- `outputs/.../pairs.txt` - List of matched image pairs
- `outputs/.../matches.h5` - Feature matches between images
- `outputs/capture/` - Intermediate data (features, descriptors, cached)

### Directory Structure

```
my_localization/
├── sessions/
│   ├── map/                          # symlink to NavVis session
│   │   ├── images.txt
│   │   ├── sensors.txt
│   │   ├── trajectories.txt
│   │   ├── raw_data/
│   │   │   ├── images_undistr_center/
│   │   │   └── pointcloud.ply
│   │   └── proc/meshes/
│   └── query_phone/
│       ├── sensors.txt               # Camera intrinsics
│       ├── images.txt                # Image paths
│       ├── queries.txt               # Images to localize
│       └── raw_data/images/
│           └── query.jpg
└── outputs/
    └── pose_estimation/.../poses.txt  # Results
```

---

## Camera Intrinsics

The script auto-estimates camera intrinsics, but you can provide exact values for better accuracy.

### Typical Phone Values

**iPhone 13/14 Pro:**
- Resolution: 4032 x 3024
- Focal: ~2822 px
- Principal point: (2016, 1512)

**Pixel 6/7:**
- Resolution: 4080 x 3072
- Focal: ~2856 px
- Principal point: (2040, 1536)

**Generic phone (estimate):**
- Focal length ≈ 0.7 × max(width, height)
- Principal point ≈ (width/2, height/2)

### Get Exact Values

- iOS: Use "Camera Intrinsics" app
- Android: Use "FreeDCam" app
- Or calibrate using [OpenCV calibration tutorial](https://github.com/opencv/opencv/blob/master/doc/tutorials/calib3d/camera_calibration/camera_calibration.markdown)

---

## Troubleshooting

### "Bus error encountered in worker"

**Problem:** Insufficient shared memory for PyTorch DataLoaders

**Solution:** Add `--shm-size=2g` to docker run command:
```bash
docker run -it --rm --init \
    --shm-size=2g \
    ...
```

### "ModuleNotFoundError: hloc"

**Problem:** Missing dependencies

**Solution:** Install dependencies:
```bash
python -m pip install -e .
```

### Slow Matching Step

**This is normal!**

- First run: 2-4 hours (matches 15,000+ image pairs to build 3D map)
- Results are cached in `outputs/`
- Subsequent runs: 1-2 minutes (only query matching needed)
- The initial slowness is necessary for accurate 3D reconstruction
- Without GPU: slower but works
- With GPU: much faster


## Next Steps

- **Multiple images:** Add more entries to `queries.txt` and `images.txt`
- **Better retrieval:** Try `--retrieval overlap` to use mesh for geometric retrieval
- **Sequence localization:** Use `--sequence_length_seconds 10` for multi-frame tracking
- **Visualization:** Load poses in MeshLab with your mesh to visualize camera positions
- **AR/VR integration:** Use predicted poses directly with your NavVis `pointcloud.ply` in Unity/Unreal

---

**For Questions:**
- Check the main [README.md](README.md)
- Review [CAPTURE.md](CAPTURE.md) for data format details
- See [RAW-DATA.md](RAW-DATA.md) for NavVis data structure

