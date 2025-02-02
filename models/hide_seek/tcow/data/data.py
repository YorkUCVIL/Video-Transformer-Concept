'''
Data loading and processing logic.
Created by Basile Van Hoorick, Jun 2022.
'''

from __init__ import *

# Internal imports.
import data_kubric
import data_mixed
import data_plugin
import data_ytvos


def _seed_worker(worker_id):
    '''
    Ensures that every data loader worker has a separate seed with respect to NumPy and Python
    function calls, not just within the torch framework. This is very important as it sidesteps
    lack of randomness- and augmentation-related bugs.
    '''
    worker_seed = torch.initial_seed() % (2 ** 32)  # This is distinct for every worker.
    np.random.seed(worker_seed)
    random.seed(worker_seed)
    
    np.set_printoptions(precision=3, suppress=True)
    torch.set_printoptions(precision=3, sci_mode=False)


def _is_kubric_source(cur_data_path):
    return ('kubcon' in cur_data_path.lower() or 'kubbench' in cur_data_path.lower())


def _is_ytvos_source(cur_data_path):
    # NOTE: Avoid checking for ytvos here, since that is how I name plugin folders!
    return ('youtube-vos' in cur_data_path.lower())


def _is_plugin_source(cur_data_path):
    return ('plugin' in cur_data_path.lower() or
            cur_data_path.lower().endswith('.mp4') or
            cur_data_path.lower().endswith('.avi') or
            cur_data_path.lower().endswith('.gif') or
            cur_data_path.lower().endswith('.webm'))


def create_train_val_data_loaders(args, logger):
    '''
    return (train_loader, val_aug_loader, val_noaug_loader, dset_args_sources).
    '''
    actual_data_paths = args.data_path
    assert isinstance(actual_data_paths, list)
    
    train_dset_sources = dict()
    val_aug_dset_sources = dict()
    val_noaug_dset_sources = dict()
    dset_args_sources = dict()
    shuffle = not(args.data_loop_only)

    for cur_data_path in actual_data_paths:
        if _is_kubric_source(cur_data_path):
            (train_dataset, val_aug_dataset, val_noaug_dataset, dset_args) = \
                create_kubric_train_val_data_loaders(args, logger, cur_data_path)
            train_dset_sources['kubric'] = train_dataset
            val_aug_dset_sources['kubric'] = val_aug_dataset
            val_noaug_dset_sources['kubric'] = val_noaug_dataset
            dset_args_sources['kubric'] = dset_args

        elif _is_ytvos_source(cur_data_path):
            (train_dataset, dset_args) = \
                create_youtube_vos_train_loader(args, logger, cur_data_path)
            train_dset_sources['ytvos'] = train_dataset
            dset_args_sources['ytvos'] = dset_args

        elif _is_plugin_source(cur_data_path):
            raise NotImplementedError('Plugin video is only available at test time.')

        else:
            raise ValueError('Unknown data path: {}'.format(cur_data_path))

    if len(train_dset_sources) == 1:
        # No mixed-batch training; variables already correctly assigned.
        final_train_dataset = train_dataset

    elif len(train_dset_sources) > 1:
        # Configure mixed-batch training with equal ratios.
        final_train_dataset = data_mixed.MixedDataset(logger, train_dset_sources,
                                                        chunk_size=args.batch_size)
        shuffle = False

    else:
        raise RuntimeError('No training datasets were successfully instantiated.')

    if len(val_aug_dset_sources) == 1:
        # No mixed-batch validation; variables already correctly assigned.
        final_val_aug_dataset = val_aug_dataset
        final_val_noaug_dataset = val_noaug_dataset

    elif len(val_aug_dset_sources) > 1:
        # Configure mixed-batch validation with equal ratios.
        final_val_aug_dataset = data_mixed.MixedDataset(logger, val_aug_dset_sources,
                                                          chunk_size=args.batch_size) \
            if args.do_val_aug else None
        final_val_noaug_dataset = data_mixed.MixedDataset(logger, val_noaug_dset_sources,
                                                            chunk_size=args.batch_size) \
            if args.do_val_noaug else None
        shuffle = False

    elif args.do_val_aug or args.do_val_noaug:
        logger.error('No validation datasets were successfully instantiated.')

    train_loader = torch.utils.data.DataLoader(
        final_train_dataset, batch_size=args.batch_size, num_workers=args.num_workers,
        shuffle=shuffle, worker_init_fn=_seed_worker, drop_last=True, pin_memory=False)
    val_aug_loader = torch.utils.data.DataLoader(
        final_val_aug_dataset, batch_size=args.batch_size, num_workers=args.num_workers,
        shuffle=shuffle, worker_init_fn=_seed_worker, drop_last=True, pin_memory=False) \
        if args.do_val_aug else None
    val_noaug_loader = torch.utils.data.DataLoader(
        final_val_noaug_dataset, batch_size=args.batch_size, num_workers=args.num_workers,
        shuffle=shuffle, worker_init_fn=_seed_worker, drop_last=True, pin_memory=False) \
        if args.do_val_noaug else None

    return (train_loader, val_aug_loader, val_noaug_loader, dset_args_sources)


def create_kubric_train_val_data_loaders(args, logger, cur_data_path):
    dset_args = dict()

    if args.which_seeker == 'point_track_3d':
        query_size = 'point'
        load_3d = True

    elif args.which_seeker == 'mask_track_2d':
        query_size = 'thing'
        load_3d = False

    dset_args['num_frames'] = args.num_frames
    dset_args['frame_height'] = args.frame_height
    dset_args['frame_width'] = args.frame_width
    dset_args['frame_rate'] = args.kubric_frame_rate
    dset_args['frame_stride'] = args.kubric_frame_stride
    dset_args['max_delay'] = args.kubric_max_delay
    dset_args['use_data_frac'] = args.use_data_frac
    dset_args['augs_2d'] = args.augs_2d
    dset_args['augs_3d'] = args.augs_3d
    dset_args['num_queries'] = args.num_queries
    dset_args['query_time'] = args.seeker_query_time
    dset_args['query_size'] = query_size
    dset_args['load_3d'] = load_3d
    dset_args['max_objects'] = 36
    dset_args['force_perturb_idx'] = args.force_perturb_idx
    dset_args['force_view_idx'] = args.force_view_idx
    dset_args['single_scene'] = args.single_scene
    dset_args['fake_data'] = args.fake_data
    dset_args['augs_version'] = args.augs_version
    dset_args['front_occl_thres'] = args.front_occl_thres
    dset_args['outer_cont_thres'] = args.outer_cont_thres
    dset_args['reverse_prob'] = args.kubric_reverse_prob
    dset_args['palindrome_prob'] = args.kubric_palindrome_prob
    dset_args['degrade'] = args.kubric_degrade
    dset_args['annot_visible_pxl_only'] = args.annot_visible_pxl_only

    train_dataset = data_kubric.KubricQueryDataset(
        cur_data_path, logger, 'train', **dset_args)
    val_aug_dataset = data_kubric.KubricQueryDataset(
        cur_data_path, logger, 'val_aug', **dset_args) if args.do_val_aug else None
    val_noaug_dataset = data_kubric.KubricQueryDataset(
        cur_data_path, logger, 'val_noaug', **dset_args) if args.do_val_noaug else None

    return (train_dataset, val_aug_dataset, val_noaug_dataset, dset_args)


def create_youtube_vos_train_loader(args, logger, cur_data_path):
    assert args.which_seeker == 'mask_track_2d'
    
    dset_args = dict()
    dset_args['num_frames'] = args.num_frames
    dset_args['frame_height'] = args.frame_height
    dset_args['frame_width'] = args.frame_width
    dset_args['frame_rate'] = args.ytvos_frame_rate
    dset_args['frame_stride'] = args.ytvos_frame_stride
    dset_args['use_data_frac'] = args.use_data_frac
    dset_args['augs_2d'] = args.augs_2d
    dset_args['query_time'] = args.seeker_query_time
    dset_args['augs_version'] = args.augs_version

    train_dataset = data_ytvos.YoutubeVOSDataset(
        cur_data_path, logger, 'train', **dset_args)

    return (train_dataset, dset_args)


def create_test_data_loader(train_args, test_args, train_dset_args_sources, logger):
    '''
    return (test_loader, test_dset_args_sources).
    '''
    # NOTE: Translating multiple plugin videos, or txt collections thereof, into multiple datasets,
    # is now done in test.py via subsequent iterations to avoid overloading server memory.
    actual_data_paths = test_args.data_path
    assert isinstance(actual_data_paths, list)
    
    # Due to the nature of testing, we will simply use ConcatDataset instead of MixedDataset here
    # when there are multiple data sources.
    test_dataset_list = []
    # NOTE: Only the last test_dset_args of each source in the list is remembered and returned.
    test_dset_args_sources = dict()
    
    for cur_data_path in actual_data_paths:

        # Upgrade variables from old to new format.
        if not('kubric' in train_dset_args_sources.keys()):
            train_dset_args_sources = {'kubric': train_dset_args_sources}
        
        if _is_kubric_source(cur_data_path):
            (test_dataset, test_dset_args) = \
                create_kubric_test_data_loader(
                    train_args, test_args, train_dset_args_sources, logger, cur_data_path)
            test_dataset_list.append(test_dataset)
            test_dset_args_sources['kubric'] = test_dset_args

        elif _is_ytvos_source(cur_data_path):
            (test_dataset, test_dset_args) = \
                create_youtube_vos_test_loader(
                    train_args, test_args, train_dset_args_sources, logger, cur_data_path)
            test_dataset_list.append(test_dataset)
            test_dset_args_sources['ytvos'] = test_dset_args

        elif _is_plugin_source(cur_data_path):
            (test_dataset, test_dset_args) = \
                create_plugin_test_data_loader(
                    train_args, test_args, train_dset_args_sources, logger, cur_data_path)
            test_dataset_list.append(test_dataset)
            test_dset_args_sources['plugin'] = test_dset_args

        else:
            raise ValueError('Unknown data path: {}'.format(cur_data_path))

    if len(test_dataset_list) == 1:
        final_test_dataset = test_dataset
    else:
        logger.info('Concatenating {} test datasets'.format(len(test_dataset_list)))
        final_test_dataset = torch.utils.data.ConcatDataset(test_dataset_list)

    shuffle = False
    test_loader = torch.utils.data.DataLoader(
        final_test_dataset, batch_size=test_args.batch_size, num_workers=test_args.num_workers,
        shuffle=shuffle, worker_init_fn=_seed_worker, drop_last=False, pin_memory=False)

    return (test_loader, test_dset_args_sources)


def create_kubric_test_data_loader(train_args, test_args, train_dset_args_sources, logger,
                                   cur_data_path):
    test_dset_args = copy.deepcopy(train_dset_args_sources['kubric'])
    
    # Fix outdated arguments from older checkpoints.
    if 'augs_version' not in test_dset_args:
        test_dset_args['augs_version'] = 1
    if 'load_full_segm' in test_dset_args:
        del test_dset_args['load_full_segm']

    # NOTE: We need to be thoughtful about which options to retain or renew here!
    # When parameters *are* reassigned here, then it means we want to explicitly allow for
    # flexibility in that aspect for evaluation purposes.
    # When parameters are *not* reassigned here, it means we do want to block the user from
    # introducing train-test domain shifts along that dimension.
    test_dset_args['single_scene'] = test_args.single_scene
    test_dset_args['fake_data'] = test_args.fake_data
    test_dset_args['use_data_frac'] = test_args.use_data_frac
    test_dset_args['augs_2d'] = False
    test_dset_args['augs_3d'] = False
    test_dset_args['num_queries'] = test_args.num_queries
    test_dset_args['force_perturb_idx'] = test_args.force_perturb_idx
    test_dset_args['force_view_idx'] = test_args.force_view_idx
    test_dset_args['degrade'] = test_args.kubric_degrade
    
    # It is very important that we test on consistent, fair, xray annotations!
    # NOTE: Actually, this flag has no effect, the mask behavior is really executed in pipeline.py.
    test_dset_args['annot_visible_pxl_only'] = False

    test_dataset = data_kubric.KubricQueryDataset(
        cur_data_path, logger, 'test', **test_dset_args)

    return (test_dataset, test_dset_args)


def create_youtube_vos_test_loader(train_args, test_args, train_dset_args_sources, logger,
                                   cur_data_path):
    test_dset_args = copy.deepcopy(train_dset_args_sources['ytvos'])
    
    # Fix outdated arguments from older checkpoints.
    if 'augs_version' not in test_dset_args:
        test_dset_args['augs_version'] = 1

    # NOTE: We need to be thoughtful about which options to retain or renew here!
    test_dset_args['use_data_frac'] = test_args.use_data_frac
    test_dset_args['augs_2d'] = False

    test_dataset = data_ytvos.YoutubeVOSDataset(
        cur_data_path, logger, 'test', **test_dset_args)

    return (test_dataset, test_dset_args)


def create_plugin_test_data_loader(train_args, test_args, train_dset_args_sources, logger,
                                   cur_data_path):
    test_dset_args = dict()
    
    # Fix outdated arguments from older checkpoints.
    if 'augs_version' not in test_dset_args:
        test_dset_args['augs_version'] = 1
    
    # NOTE: We need to be thoughtful about which options to retain or renew here!
    # Frame rate and frame stride are mostly for later interpretation / sorting.
    test_dset_args['num_clip_frames'] = train_dset_args_sources['kubric']['num_frames']
    test_dset_args['frame_height'] = train_dset_args_sources['kubric']['frame_height']
    test_dset_args['frame_width'] = train_dset_args_sources['kubric']['frame_width']
    test_dset_args['frame_rate'] = test_args.plugin_frame_rate
    test_dset_args['prefer_frame_stride'] = test_args.plugin_prefer_frame_stride
    test_dset_args['multiplicity'] = 12  # Currently unused.
    test_dset_args['query_time'] = train_dset_args_sources['kubric']['query_time']
    test_dset_args['augs_version'] = train_dset_args_sources['kubric']['augs_version']
    test_dset_args['annots_must_exist'] = test_args.annots_must_exist
    
    # OLD: Too many problems / slowdowns otherwise.
    # test_dset_args['prefetch'] = False
    # NEW: Coupled with outer test iterations, we ensure this way only one large video is held in
    # memory at a time.
    test_dset_args['prefetch'] = True
    
    test_dset_args['center_crop'] = test_args.center_crop
    
    test_dataset = data_plugin.PluginVideoDataset(
        cur_data_path, logger, 'test', **test_dset_args)

    return (test_dataset, test_dset_args)


class StubDataset(torch.utils.data.Dataset):

    def __init__(self, dataset_size):
        self.dataset_size = dataset_size

    def __len__(self):
        return self.dataset_size

    def __getitem__(self, index):
        data_retval = dict()
        data_retval['dset_idx'] = index
        return data_retval
