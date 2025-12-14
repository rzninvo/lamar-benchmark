#!/usr/bin/env python3
"""
Simple script to localize a single phone image against a NavVis map.

Usage:
    python localize_single_image.py \
        --map_path /path/to/navvis_session \
        --query_image /path/to/your/image.jpg \
        --output_dir ./outputs
"""

import sys
from pathlib import Path

# Add parent directory to path to import lamar and scantools
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import numpy as np

from scantools.capture import Capture, Session, Sensors, Camera, Trajectories, RecordsCamera, Pose
from scantools.capture import create_sensor
from lamar.tasks import (
    FeatureExtraction, PairSelection, FeatureMatching, Mapping, PoseEstimation
)


def create_simple_query_session(capture: Capture,
                                  query_image_path: Path,
                                  session_id: str = "query_single"):
    """Create a minimal query session with a single image."""

    # Create session directory
    session_path = capture.session_path(session_id)
    session_path.mkdir(exist_ok=True, parents=True)

    # Create raw_data directory and copy image
    raw_data = capture.data_path(session_id) / "images"
    raw_data.mkdir(exist_ok=True, parents=True)

    import shutil
    image_name = "query.jpg"
    dest_image = raw_data / image_name
    shutil.copy2(query_image_path, dest_image)

    # Create a simple camera (you may need to adjust these intrinsics)
    # These are typical phone camera parameters - adjust to your camera
    from PIL import Image
    img = Image.open(query_image_path)
    width, height = img.size

    # Rough estimate: focal length ~0.7 * max(width, height)
    focal = 0.7 * max(width, height)
    cx, cy = width / 2, height / 2

    sensors = Sensors()
    camera = create_sensor('camera', ['PINHOLE', width, height, focal, focal, cx, cy],
                          name='Phone camera')
    sensors['camera'] = camera

    # Create image records
    images = RecordsCamera()
    timestamp = 1000000  # arbitrary timestamp
    images[timestamp, 'camera'] = str(Path("images") / image_name)

    # Create trajectory (identity pose - we don't know the true pose)
    trajectories = Trajectories()
    # Not needed for queries without ground truth

    # Save session
    sensors.save(session_path / 'sensors.txt')
    images.save(session_path / 'images.txt')

    # Create queries.txt - list of images to localize
    with open(session_path / 'queries.txt', 'w') as f:
        f.write(f'{timestamp}, camera\n')

    # Reload session
    capture.sessions[session_id] = Session.load(session_path)

    return session_id


def localize_image(map_path: Path,
                   query_image: Path,
                   output_dir: Path,
                   capture_dir: Path = None):
    """Localize a single image against a NavVis map."""

    # Set up capture structure
    if capture_dir is None:
        capture_dir = output_dir / "capture"
    capture_dir.mkdir(exist_ok=True, parents=True)

    sessions_dir = capture_dir / "sessions"
    sessions_dir.mkdir(exist_ok=True, parents=True)

    # Link/copy map session
    map_link = sessions_dir / "map"
    if not map_link.exists():
        print(f"Creating symlink to map: {map_path} -> {map_link}")
        map_link.symlink_to(map_path.absolute())

    # Clean up any existing query session
    query_session_dir = sessions_dir / "query_single"
    if query_session_dir.exists():
        import shutil
        print(f"Removing existing query session: {query_session_dir}")
        shutil.rmtree(query_session_dir)

    # Load capture
    capture = Capture.load(capture_dir)

    # Create query session with single image
    print(f"Creating query session with image: {query_image}")
    query_id = create_simple_query_session(capture, query_image, "query_single")

    # Run localization pipeline
    ref_id = "map"

    print("\n=== Running Localization Pipeline ===")
    print(f"Reference session: {ref_id}")
    print(f"Query session: {query_id}")
    print(f"Output directory: {output_dir}")

    # Configuration - using NetVLAD for retrieval (compatible with PyTorch 2.6)
    # Note: 'fusion' requires AP-GeM which has compatibility issues with PyTorch 2.6+
    configs = {
        'extraction': FeatureExtraction.methods['superpoint'],
        'pairs_map': {
            'method': PairSelection.methods['netvlad'],
            'num_pairs': 10,
            'filter_frustum': {'do': True},
            'filter_pose': {'do': True, 'num_pairs_filter': 250},
        },
        'matching': FeatureMatching.methods['superglue'],
        'mapping': Mapping.methods['triangulation'],
        'pairs_loc': {
            'method': PairSelection.methods['netvlad'],
            'num_pairs': 10,
        },
        'poses': PoseEstimation.methods['single_image'],
    }

    # Read query list
    from lamar.utils.capture import read_query_list
    query_list_path = capture.session_path(query_id) / 'queries.txt'
    query_list = read_query_list(query_list_path)

    print(f"\n1. Extracting features from map session...")
    extraction_map = FeatureExtraction(output_dir, capture, ref_id, configs['extraction'])

    print(f"\n2. Selecting image pairs for mapping...")
    pairs_map = PairSelection(output_dir, capture, ref_id, ref_id, configs['pairs_map'])

    print(f"\n3. Matching features for mapping...")
    matching_map = FeatureMatching(
        output_dir, capture, ref_id, ref_id, configs['matching'],
        pairs_map, extraction_map)

    print(f"\n4. Building 3D map via triangulation...")
    mapping = Mapping(
        configs['mapping'], output_dir, capture, ref_id,
        extraction_map, matching_map)

    print(f"\n5. Extracting features from query image...")
    extraction_query = FeatureExtraction(
        output_dir, capture, query_id, configs['extraction'], query_list)

    print(f"\n6. Selecting retrieval pairs for localization...")
    pairs_loc = PairSelection(
        output_dir, capture, query_id, ref_id, configs['pairs_loc'],
        query_list, query_poses=None)

    print(f"\n7. Matching query features to map...")
    matching_query = FeatureMatching(
        output_dir, capture, query_id, ref_id, configs['matching'],
        pairs_loc, extraction_query, extraction_map)

    print(f"\n8. Estimating camera pose...")
    pose_estimation = PoseEstimation(
        configs['poses'], output_dir, capture, query_id,
        extraction_query, matching_query, mapping, query_list)

    # Get result
    poses = pose_estimation.poses

    print("\n=== Results ===")

    # Show matched candidate images
    pairs_file = pairs_loc.paths.pairs_hloc
    if pairs_file.exists():
        print(f"\n📸 Candidate map images matched against query:")
        with open(pairs_file, 'r') as f:
            pairs = [line.strip().split() for line in f.readlines()]
            print(f"  Found {len(pairs)} candidate images:")
            for i, pair in enumerate(pairs[:10], 1):  # Show first 10
                if len(pair) >= 2:
                    map_img = pair[1]
                    print(f"    {i}. {map_img}")
            if len(pairs) > 10:
                print(f"    ... and {len(pairs) - 10} more")
        print(f"\n  Full list saved to: {pairs_file}")

    if len(poses) > 0:
        query_key = query_list[0]
        if query_key in poses.key_pairs():
            T_w_cam = poses[query_key]
            print(f"\n✓ Successfully localized!")
            print(f"  Position: {T_w_cam.t}")
            print(f"  Rotation (quaternion): {T_w_cam.r.as_quat()}")
            print(f"\nPose saved to: {pose_estimation.paths.poses}")
        else:
            print(f"\n✗ Localization failed - could not estimate pose")
            print(f"  Possible reasons:")
            print(f"  - Not enough feature matches with map images")
            print(f"  - Query image too different from map images")
            print(f"  - Query image outside mapped area")
    else:
        print(f"\n✗ No poses estimated")

    return pose_estimation


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Localize a single image against a NavVis map')
    parser.add_argument('--map_path', type=Path, required=True,
                       help='Path to NavVis session (map)')
    parser.add_argument('--query_image', type=Path, required=True,
                       help='Path to query image')
    parser.add_argument('--output_dir', type=Path, default=Path('./outputs'),
                       help='Output directory for results')

    args = parser.parse_args()

    # Validate inputs
    if not args.map_path.exists():
        raise FileNotFoundError(f"Map path not found: {args.map_path}")
    if not args.query_image.exists():
        raise FileNotFoundError(f"Query image not found: {args.query_image}")

    args.output_dir.mkdir(exist_ok=True, parents=True)

    # Run localization
    localize_image(args.map_path, args.query_image, args.output_dir)

