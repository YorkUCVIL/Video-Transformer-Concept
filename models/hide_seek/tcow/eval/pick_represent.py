'''
Process representative subset of test results.
Created by Basile Van Hoorick, Nov 2022.
'''


import os
import sys
sys.path.insert(0, os.path.join(os.getcwd(), 'eval/'))
sys.path.insert(0, os.getcwd())

from __init__ import *

# Library imports.
import glob
import json
import warnings

# Internal imports.
import args
import logvisgen
import metrics
import my_utils

warnings.simplefilter(action='ignore', category=FutureWarning)


def get_args():

    parser = argparse.ArgumentParser()

    parser.add_argument('--testres_path', required=True, type=str, nargs='+',
                        help='Path(s) to test log folder(s).')
    parser.add_argument('--represent_guide', required=True, type=str, nargs='+',
                        help='Path(s) to list(s) of file masks for clips of interest.')
    parser.add_argument('--output_dir', required=True, type=str,
                        help='Path of collection to copy representative data to.')
    parser.add_argument('--notes_path', default='', type=str,
                        help='For easier bookkeeping, attach these custom comments/tags next to '
                        'models and test results .')
    parser.add_argument('--video_suffix', default=['in.webm', 'out_oc.webm', 'out_sn.webm'], type=str, nargs='+',
                        help='Path of collection to copy representative data to.')
    parser.add_argument('--no_video_copy_for', default=['kubcon'], type=str,
                        help='Guide file name subsets for which to just calculate averages, but '
                        'skip video copying.')
    parser.add_argument('--write_summary', default=True, type=args._str2bool,
                        help='Gather CSV table of (model, guide, metric) values and export to '
                             'same output directory.')

    my_args = parser.parse_args()
    return my_args


def main(my_args, logger):

    actual_testres_paths = []
    for dp in my_args.testres_path:
        dps = glob.glob(dp)  # Parses wildcards and turns them into available matching folders.
        actual_testres_paths += dps
    logger.info(f'Found {len(actual_testres_paths)} test result folders: '
                f'{[str(pathlib.Path(x).name) for x in actual_testres_paths]}')

    actual_guide_paths = []
    for fp in my_args.represent_guide:
        fps = glob.glob(fp)
        actual_guide_paths += fps
    logger.info(f'Found {len(actual_guide_paths)} guide files: '
                f'{[str(pathlib.Path(x).name) for x in actual_guide_paths]}')

    model_notes = dict()
    if len(my_args.notes_path) > 0 and os.path.exists(my_args.notes_path):
        notes_lines = my_utils.read_txt_strip_comments(my_args.notes_path)
        for line in notes_lines:
            (testres_pat, cur_note) = line.split('=')[:2]
            model_notes[testres_pat.strip()] = cur_note.strip()

    summary = construct_summary(
        my_args, actual_guide_paths, actual_testres_paths, model_notes)

    summary = merge_cross_dataset_guides(
        my_args, summary, actual_guide_paths, actual_testres_paths, model_notes)

    # Export summary.
    if my_args.write_summary:
        summary_idx = -1
        summary_fp = None
        while summary_fp is None or os.path.exists(summary_fp):
            summary_idx += 1
            summary_fp = os.path.join(my_args.output_dir, f'_autosmr_{summary_idx}.csv')

        # summary = summary.sort_index(axis=1)  # Sort horizontally by column name.
        summary.to_csv(summary_fp)

    logger.info('Done!')


def construct_summary(
        my_args, actual_guide_paths, actual_testres_paths, model_notes):

    summary = pd.DataFrame()

    for cur_guide_fp in tqdm.tqdm(actual_guide_paths):

        # NOTE: Entries in guide refer to part of friendly_short_name (AND also scene_dn if two
        # comma-separated patterns are specified)!
        guide_name = str(pathlib.Path(cur_guide_fp).name).split('.')[0]
        logger.info(f'Processing guide {cur_guide_fp}...')

        lines = sorted(my_utils.read_txt_strip_comments(cur_guide_fp))
        if len(lines) == 0:
            logger.warning(f'Guide {guide_name} seems empty? Skipping...')
            continue

        for src_dp in tqdm.tqdm(actual_testres_paths):

            src_csv_fp = os.path.join(src_dp, 'itemized_results.csv')
            if not os.path.exists(src_csv_fp):
                logger.warning(f'CSV file not found: {src_csv_fp}! Skipping...')
                continue

            # Filter & export numerical results.
            csv = pd.read_csv(src_csv_fp)
            csv.drop(columns=csv.columns[0])  # Remove unnamed index.
            agg_mask = csv['friendly_short_name'].str.contains(lines[0])

            for cand_rep in lines[0:]:
                if ',' in cand_rep and 'scene_dn' in csv.columns:
                    cand_scene = cand_rep.split(',')[0]
                    cand_friendly = cand_rep.split(',')[1]
                    cur_mask = csv['scene_dn'].str.contains(cand_scene)
                    if len(cand_friendly) > 0:
                        cur_mask = cur_mask & csv['friendly_short_name'].str.contains(cand_friendly)
                else:
                    cur_mask = csv['friendly_short_name'].str.contains(cand_rep)

                agg_mask = agg_mask | cur_mask

            sel_csv = csv[agg_mask]
            num_examples = len(sel_csv)

            if num_examples == 0:
                # logger.warning(f'No representative results found in {src_csv_fp}! Skipping...')
                continue

            src_dn = str(pathlib.Path(src_dp).name)
            dst_dn = src_dn + '_ar_' + guide_name
            dst_dp = os.path.join(my_args.output_dir, dst_dn)
            os.makedirs(dst_dp, exist_ok=True)
            dst_csv_fp = os.path.join(dst_dp, f'z_filt_item_res_{guide_name}.csv')
            if os.path.exists(dst_csv_fp):
                os.remove(dst_csv_fp)
            sel_csv.to_csv(dst_csv_fp)

            # Calculate and neatly summarize aggregate statistics for this (test, guide) pair.
            final_weighted_metrics = metrics.calculate_weighted_averages_dataframe(sel_csv)
            final_unweighted_metrics = metrics.calculate_unweighted_averages_dataframe(sel_csv)

            # Filter to ensure positive counts only.
            final_weighted_metrics = {k: v for (k, v) in sorted(final_weighted_metrics.items())
                                      if ('count' in k and v > 0) or ('mean' in k and v > -1.0)}
            final_unweighted_metrics = {k: v for (k, v) in sorted(final_unweighted_metrics.items())
                                        if ('count' in k and v > 0) or ('mean' in k and v > -1.0)}

            with open(os.path.join(dst_dp, f'z_metrics_{guide_name}.txt'), 'w') as f:
                f.writelines(f'Logs: {src_dn}\n')
                f.writelines(f'Guide: {guide_name}\n')
                f.writelines(f'Selected number of examples: {num_examples}\n')
                f.writelines('\nWeighted:\n')
                f.writelines([f'{k}: {v:}\n'
                              for (k, v) in sorted(final_weighted_metrics.items())])
                f.writelines('\nUnweighted:\n')
                f.writelines([f'{k}: {v:}\n'
                              for (k, v) in sorted(final_unweighted_metrics.items())])

            # Copy representative videos corresponding to selected rows.
            if any([x in guide_name.lower() for x in my_args.no_video_copy_for]):
                logger.info('Skipping video copy...')

            else:
                logger.info('Copying videos matching desired suffices...')
                src_vid_fps = []
                for idx, row in sel_csv.iterrows():
                    for suffix in my_args.video_suffix:
                        matches = glob.glob(os.path.join(
                            src_dp, 'visuals', '*' + row['friendly_short_name'] + '*' + suffix))
                        src_vid_fps += matches

                src_vid_fps = sorted(list(set(src_vid_fps)))
                for src_vid_fp in src_vid_fps:
                    src_vid_fn = str(pathlib.Path(src_vid_fp).name)
                    dst_vid_fp = os.path.join(dst_dp, src_vid_fn)
                    if not(os.path.exists(dst_vid_fp)):
                        shutil.copyfile(src_vid_fp, dst_vid_fp)

            # Attach custom note if found.
            note_dict = {'notes': ' '}
            for testres_pat in model_notes.keys():
                if testres_pat in src_dn:
                    note_dict = {'notes': model_notes[testres_pat]}
                    break

            # To avoid confusing cross-dataset aggregations with perfect baselines, we put the
            # baseline type in front of the shorthand test result name.
            fixed_dn = src_dn
            if '_pb' in src_dn:
                fixed_dn = 'test_pb' + src_dn.split('_pb')[-1] + '_' + src_dn.split('_')[2]

            # Update summary.
            summary = summary.append({
                'guide': guide_name,
                'testres_dn': fixed_dn,
                **note_dict,
                'num_examples': num_examples,
                **{'weighted_' + k: v for (k, v) in final_weighted_metrics.items()},
                **{'unweighted_' + k: v for (k, v) in final_unweighted_metrics.items()},
            }, ignore_index=True)

            logger.info(f'Subselected {num_examples} entries for: {src_dn}')

        logger.info()

    return summary


def merge_cross_dataset_guides(
        my_args, summary, actual_guide_paths, actual_testres_paths, model_notes):

    # Merge cross-dataset guides as long as they are from the same model.
    # This typically adds extra lines to the automatic summary, but will not copy more videos.
    new_summary = copy.deepcopy(summary)

    model_pats = []
    for src_dp in actual_testres_paths:
        src_dn = str(pathlib.Path(src_dp).name)  # test_v111_d8_e69
        model_pats.append('_'.join(src_dn.split('_')[0:2]))
    model_pats = list(set(model_pats))

    for cur_guide_fp in actual_guide_paths:
        guide_name = str(pathlib.Path(cur_guide_fp).name).split('.')[0]  # rdy_v2_m_nl
        dst_guide_name = 'cd_' + guide_name  # CD = cross dataset (typically markers *_m_*).

        for model_pat in model_pats:
            sel_rows = pd.DataFrame()
            for i, row in summary.iterrows():
                if row['guide'] == guide_name and model_pat in row['testres_dn']:
                    sel_rows = sel_rows.append(row, ignore_index=True)

            # NOTE / WARNING / DEBUG: We hardcoded rdy markers to be always cd here!
            if sel_rows.shape[0] == 0 or (not('_m_' in guide_name) and sel_rows.shape[0] <= 1):
                continue
                
            # WARNING: We must calculate just WEIGHTED here, because we are already working with
            # weighted & unweighted averages with different counts over either frames or scenes!
            merged_metrics = metrics.calculate_weighted_averages_dataframe(sel_rows)

            # Filter to ensure positive counts only.
            merged_metrics = {k: v for (k, v) in sorted(merged_metrics.items())
                            if ('count' in k and v > 0) or ('mean' in k and v > -1.0)}

            # Attach custom note if found.
            note_dict = {'notes': ' '}
            for testres_pat in model_notes.keys():
                if testres_pat in model_pat:
                    note_dict = {'notes': model_notes[testres_pat]}
                    break

            # Update summary.
            new_summary = new_summary.append({
                'guide': dst_guide_name,
                'testres_dn': model_pat,  # This is just a prefix in this case.
                **note_dict,
                # NOTE: num_examples is not kept track of anymore here.
                **merged_metrics,
            }, ignore_index=True)

            # Copy representative videos matching this (guide, model) pair.
            dst_vid_dp = os.path.join(my_args.output_dir, dst_guide_name + '_' + model_pat)
            os.makedirs(dst_vid_dp, exist_ok=True)
            for vid_dn in os.listdir(my_args.output_dir):
                if '_' + guide_name in vid_dn and model_pat in vid_dn:
                    src_vid_dp = os.path.join(my_args.output_dir, vid_dn)
                    for vid_fn in os.listdir(src_vid_dp):
                        for suffix in my_args.video_suffix:
                            if vid_fn.lower().endswith(suffix):
                                src_vid_fp = os.path.join(src_vid_dp, vid_fn)
                                dst_vid_fp = os.path.join(dst_vid_dp, vid_fn)
                                if not(os.path.exists(dst_vid_fp)):
                                    shutil.copyfile(src_vid_fp, dst_vid_fp)

    return new_summary


if __name__ == '__main__':

    np.set_printoptions(precision=3, suppress=True)
    torch.set_printoptions(precision=3, sci_mode=False)

    my_args = get_args()

    logger = logvisgen.Logger(context='pickrep')

    main(my_args, logger)
