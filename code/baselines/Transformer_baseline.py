import numpy as np

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import os

wandb = False

if wandb:
    import wandb

    # wandb.offline
    os.environ['WANDB_SILENT']="true"
    wandb.login(key=str('14734fe9c5574e019e8f517149a20d6fe1b2fd0d'))
    config = wandb.config
    # run = wandb.init(project='WBtest', config={'wandb_nb':'wandb_three_in_one_hm'})
    run = wandb.init(project='Raindrop', entity='xiang_zhang', config={'wandb_nb':'wandb_three_in_one_hm'})


from sklearn.metrics import roc_auc_score, classification_report, confusion_matrix, precision_score, recall_score, f1_score
from sklearn.metrics import average_precision_score

import sys
# os.path.abspath('../')
# sys.path.append(os.path.abspath('../'))

from models import TransformerModel, TransformerModel2, Simple_classifier
from utils_baselines import *
from PAMAP2_dataset import one_hot

# from utils_phy12 import *

torch.manual_seed(1)

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--dataset', type=str, default='PAMAP2', choices=['P12', 'P19', 'eICU', 'PAMAP2'])
parser.add_argument('--withmissingratio', default=False, help='if True, missing ratio ranges from 0 to 0.5; if False, missing ratio =0')
parser.add_argument('--splittype', type=str, default='random', choices=['random', 'age', 'gender'], help='only use for P12 and P19')
parser.add_argument('--reverse', default=False, help='if True, use female, older for training; if False, use female or younger for training')
parser.add_argument('--feature_removal_level', type=str, default='set', choices=['no_removal', 'set', 'sample'],
                    help='use this only when splittype==random; otherwise, set as no_removal')
# args = parser.parse_args() #args=[]
args, unknown = parser.parse_known_args()

# training modes
arch = 'standard'

model_path = '../../models/'

dataset = args.dataset     # possible values: 'P12', 'P19', 'eICU', 'PAMAP2'
print('Dataset used: ', dataset)

if dataset == 'P12':
    base_path = '../../P12data'
elif dataset == 'P19':
    base_path = '../../P19data'
elif dataset == 'eICU':
    base_path = '../../eICUdata'
elif dataset == 'PAMAP2':
    base_path = '../../PAMAP2data'

# ### show the names of variables and statistic descriptors
# ts_params = np.load(base_path + '/processed_data/ts_params.npy', allow_pickle=True)
# extended_static_params = np.load(base_path + '/processed_data/extended_static_params.npy', allow_pickle=True)
# print('ts_params: ', ts_params)
# print('extended_static_params: ', extended_static_params)

# """Xiang"""
# base_path = '../Theo/Transformer-Irregular'
ts_params= ['ALP', 'ALT', 'AST', 'Albumin', 'BUN', 'Bilirubin', 'Cholesterol', 'Creatinine',
 'DiasABP', 'FiO2', 'GCS', 'Glucose', 'HCO3', 'HCT', 'HR', 'K', 'Lactate', 'MAP',
 'MechVent', 'Mg', 'NIDiasABP', 'NIMAP', 'NISysABP', 'Na', 'PaCO2', 'PaO2',
 'Platelets', 'RespRate', 'SaO2', 'SysABP', 'Temp', 'TroponinI', 'TroponinT',
 'Urine', 'WBC', 'pH']
extended_static_params=['Age', 'Gender=0', 'Gender=1', 'Height', 'ICUType=1', 'ICUType=2', 'ICUType=3',
 'ICUType=4', 'Weight']


feature_removal_level = args.feature_removal_level   # possible values: 'sample', 'set'

if args.withmissingratio == True:
    missing_ratios = [0.1, 0.2, 0.3, 0.4, 0.5]  # if True, with missing ratio, 0.1, 0.2, 0.3, 0.4, 0.5
else:
    missing_ratios = [0]

for missing_ratio in missing_ratios:
    # training/model params
    num_epochs = 20
    learning_rate = 0.001

    if dataset == 'P12':
        d_static = 9
        d_inp = 36
        static_info = 1
    elif dataset == 'P19':
        d_static = 6
        d_inp = 34
        static_info = 1
    elif dataset == 'eICU':
        d_static = 399
        d_inp = 14
        static_info = 1
    elif dataset == 'PAMAP2':
        d_static = 0
        d_inp = 17
        static_info = None  # if dataset is PAMAP2, set this as None

    # emb_len     = 10

    d_model = 36  # 256
    nhid = 2 * d_model
    # nhid = 256
    # nhid = 512  # seems to work better than 2*d_model=256
    # nhid = 1024
    nlayers = 1  # 2  # the layer doesn't really matters

    # nhead = 16 # seems to work better
    nhead = 1  # 8, 16, 32

    dropout = 0.3

    if dataset == 'P12':
        max_len = 215
        n_classes = 2
    elif dataset == 'P19':
        max_len = 60
        n_classes = 2
    elif dataset == 'eICU':
        max_len = 300
        n_classes = 2
    elif dataset == 'PAMAP2':
        max_len = 600
        n_classes = 8

    aggreg = 'mean'
    # aggreg = 'max'

    # MAX = d_model
    MAX = 100

    n_runs = 1  # change this from 1 to 1, in order to save debugging time.
    n_splits = 5  # change this from 5 to 1, in order to save debugging time.
    subset = False  # use subset for better debugging in local PC, which only contains 1200 patients

    """split = 'random', 'age', 'gender"""
    """reverse= True: male, age<65 for training. 
     reverse=False: female, age>65 for training"""
    """baseline=True: run baselines. False: run our model (Raindrop)"""
    split = args.splittype    # possible values: 'random', 'age', 'gender'
    reverse = args.reverse
    baseline = True

    acc_arr = np.zeros((n_splits, n_runs))
    auprc_arr = np.zeros((n_splits, n_runs))
    auroc_arr = np.zeros((n_splits, n_runs))
    precision_arr = np.zeros((n_splits, n_runs))
    recall_arr = np.zeros((n_splits, n_runs))
    F1_arr = np.zeros((n_splits, n_runs))
    for k in range(n_splits):
        split_idx = k + 1
        print('Split id: %d' % split_idx)

        if dataset == 'P12':
            if subset == True:
                split_path = '/splits/phy12_split_subset' + str(split_idx) + '.npy'
            else:
                split_path = '/splits/phy12_split' + str(split_idx) + '.npy'
        elif dataset == 'P19':
            split_path = '/splits/phy19_split' + str(split_idx) + '_new.npy'
        elif dataset == 'eICU':
            split_path = '/splits/eICU_split' + str(split_idx) + '.npy'
        elif dataset == 'PAMAP2':
            split_path = '/splits/PAMAP2_split_' + str(split_idx) + '.npy'

        # prepare the data:
        Ptrain, Pval, Ptest, ytrain, yval, ytest = get_data_split(base_path, split_path, split_type=split,
                                                                  reverse=reverse, baseline=baseline, dataset=dataset)
        print(len(Ptrain), len(Pval), len(Ptest), len(ytrain), len(yval), len(ytest))

        if dataset == 'P12' or dataset == 'P19' or dataset == 'eICU':
            T, F = Ptrain[0]['arr'].shape
            D = len(Ptrain[0]['extended_static'])
            print(T, F, D)

            # get mean, std stats from train set
            Ptrain_tensor = np.zeros((len(Ptrain), T, F))  # shape: (9600, 215, 36)
            Ptrain_static_tensor = np.zeros((len(Ptrain), D))  # shape: (9600, 9)

            # feed features to tensor. This step can be improved
            for i in range(len(Ptrain)):
                Ptrain_tensor[i] = Ptrain[i]['arr']
                Ptrain_static_tensor[i] = Ptrain[i]['extended_static']

            """Z-score Normalization. Before this step, we can remove Direct current shift (minus the average) """
            mf, stdf = getStats(Ptrain_tensor)
            ms, ss = getStats_static(Ptrain_static_tensor, dataset=dataset)

            Ptrain_tensor, Ptrain_static_tensor, Ptrain_time_tensor, ytrain_tensor = tensorize_normalize(Ptrain, ytrain,
                                                                                                         mf,
                                                                                                         stdf, ms, ss)
            Pval_tensor, Pval_static_tensor, Pval_time_tensor, yval_tensor = tensorize_normalize(Pval, yval, mf, stdf,
                                                                                                 ms, ss)
            Ptest_tensor, Ptest_static_tensor, Ptest_time_tensor, ytest_tensor = tensorize_normalize(Ptest, ytest, mf,
                                                                                                     stdf, ms,
                                                                                                     ss)

            print(Ptrain_tensor.shape, Ptrain_static_tensor.shape, Ptrain_time_tensor.shape, ytrain_tensor.shape)
            # the shapes are: torch.Size([960, 215, 72]) torch.Size([960, 9]) torch.Size([960, 215, 1]) torch.Size([960])

        elif dataset == 'PAMAP2':
            T, F = Ptrain[0].shape
            D = 1
            print(T, F, D)

            # get mean, std stats from train set
            Ptrain_tensor = Ptrain
            Ptrain_static_tensor = np.zeros((len(Ptrain), D))

            mf, stdf = getStats(Ptrain)
            Ptrain_tensor, Ptrain_static_tensor, Ptrain_time_tensor, ytrain_tensor = tensorize_normalize_other(Ptrain, ytrain, mf, stdf)
            Pval_tensor, Pval_static_tensor, Pval_time_tensor, yval_tensor = tensorize_normalize_other(Pval, yval, mf, stdf)
            Ptest_tensor, Ptest_static_tensor, Ptest_time_tensor, ytest_tensor = tensorize_normalize_other(Ptest, ytest, mf, stdf)

        # remove part of variables in validation and test set
        if missing_ratio > 0:
            num_all_features = Pval_tensor.shape[2] # int(Pval_tensor.shape[2] / 2)#  Pval_tensor.shape[2] #   # divided by 2, because of mask
            num_missing_features = round(missing_ratio * num_all_features)
            if feature_removal_level == 'sample':
                for i, patient in enumerate(Pval_tensor):
                    idx = np.random.choice(num_all_features, num_missing_features, replace=False)
                    patient[:, idx] = torch.zeros(Pval_tensor.shape[1], num_missing_features)  # values
                    # patient[:, idx + num_all_features] = torch.zeros(Pval_tensor.shape[1], num_missing_features)  # masks
                    Pval_tensor[i] = patient
                for i, patient in enumerate(Ptest_tensor):
                    idx = np.random.choice(num_all_features, num_missing_features, replace=False)
                    patient[:, idx] = torch.zeros(Ptest_tensor.shape[1], num_missing_features)   # values
                    # patient[:, idx + num_all_features] = torch.zeros(Ptest_tensor.shape[1], num_missing_features)  # masks
                    Ptest_tensor[i] = patient
            elif feature_removal_level == 'set':
                # if dataset == 'P12':
                #     dataset_prefix = ''
                # elif dataset == 'P19':
                #     dataset_prefix = 'P19_'
                # elif dataset == 'eICU':
                #     dataset_prefix = 'eICU_'
                # density_score_indices = np.load('saved/' + dataset_prefix + 'density_scores.npy', allow_pickle=True)[:, 0]
                density_score_indices = np.load('saved/IG_density_scores_' + dataset + '.npy', allow_pickle=True)[:, 0]
                # num_missing_features = num_missing_features * 2
                idx = density_score_indices[:num_missing_features].astype(int)
                Pval_tensor[:, :, idx] = torch.zeros(Pval_tensor.shape[0], Pval_tensor.shape[1], num_missing_features)   # values
                # Pval_tensor[:, :, idx + num_all_features] = torch.zeros(Pval_tensor.shape[0], Pval_tensor.shape[1], num_missing_features)  # masks
                Ptest_tensor[:, :, idx] = torch.zeros(Ptest_tensor.shape[0], Ptest_tensor.shape[1], num_missing_features)   # values
                # Ptest_tensor[:, :, idx + num_all_features] = torch.zeros(Ptest_tensor.shape[0], Ptest_tensor.shape[1], num_missing_features)  # masks

        # convert to (seq_len, batch, feats)
        Ptrain_tensor = Ptrain_tensor.permute(1, 0, 2)  # shape: [215, 960, 72]
        Pval_tensor = Pval_tensor.permute(1, 0, 2)
        Ptest_tensor = Ptest_tensor.permute(1, 0, 2)

        # convert to (seq_len, batch)
        Ptrain_time_tensor = Ptrain_time_tensor.squeeze(2).permute(1, 0)
        Pval_time_tensor = Pval_time_tensor.squeeze(2).permute(1, 0)
        Ptest_time_tensor = Ptest_time_tensor.squeeze(2).permute(1, 0)

        for m in range(n_runs):
            print('- - Run %d - -' % (m + 1))

            # instantiate model
            if dataset == 'P12' or dataset == 'P19' or dataset == 'eICU':
                model = TransformerModel2(d_inp, d_model, nhead, nhid, nlayers, dropout, max_len,
                                          d_static, MAX, 0.5, aggreg, n_classes)
            elif dataset == 'PAMAP2':
                model = TransformerModel2(d_inp, d_model, nhead, nhid, nlayers, dropout, max_len,
                                          d_static, MAX, 0.5, aggreg, n_classes, static=False)

            # model = Simple_classifier(d_inp, d_model, nhead, nhid, nlayers, dropout, max_len,
            #                           d_static, MAX, 0.5, aggreg, n_classes)

            model = model.cuda()

            criterion = torch.nn.CrossEntropyLoss().cuda()

            optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
            scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.1,
                                                                   patience=1, threshold=0.0001, threshold_mode='rel',
                                                                   cooldown=0, min_lr=1e-8, eps=1e-08, verbose=True)

            idx_0 = np.where(ytrain == 0)[0]
            idx_1 = np.where(ytrain == 1)[0]

            if dataset == 'P12' or dataset == 'P19' or dataset == 'eICU':
                strategy = 2
            elif dataset == 'PAMAP2':
                strategy = 3

            """Upsampling, increase the number of positive samples"""
            # Strategy 2: permute randomly each index set at each epoch, and expand x3 minority set
            n0, n1 = len(idx_0), len(idx_1)
            expanded_idx_1 = np.concatenate([idx_1, idx_1, idx_1], axis=0)
            expanded_n1 = len(expanded_idx_1)

            batch_size = 128  # balanced batch size
            if strategy == 1:
                n_batches = 10  # number of batches to process per epoch
            elif strategy == 2:
                K0 = n0 // int(batch_size / 2)
                K1 = expanded_n1 // int(batch_size / 2)
                n_batches = np.min([K0, K1])
            elif strategy == 3:
                n_batches = 30

            best_aupr_val = best_auc_val = 0.0
            print('Stop epochs: %d, Batches/epoch: %d, Total batches: %d' % (num_epochs, n_batches, num_epochs * n_batches))
            #         optimizer = NoamOpt(d_model, 5.0, 500, torch.optim.Adam(model.parameters(), lr=0, betas=(0.9, 0.98), eps=1e-9))

            start = time.time()
            if wandb:
                wandb.watch(model)
            for epoch in range(num_epochs):
                model.train()

                if strategy == 2:
                    """shuffle the index of positive and negative samples"""
                    np.random.shuffle(expanded_idx_1)
                    I1 = expanded_idx_1
                    np.random.shuffle(idx_0)
                    I0 = idx_0
                    # # random shuffling of expanded_idx_1, idx_0
                    # ep1 = np.random.permutation(expanded_n1)
                    # p0 = np.random.permutation(n0)
                    # I1 = expanded_idx_1[ep1]
                    # I0 = idx_0[p0]
                """In each epoch, first shuffle the samples, then take the first n_batches*int(batch_size / 2) for training"""

                for n in range(n_batches):
                    if strategy == 1:
                        idx = random_sample(idx_0, idx_1, batch_size)
                    elif strategy == 2:
                        """In each batch=128, 64 positive samples, 64 negative samples"""
                        idx0_batch = I0[n * int(batch_size / 2):(n + 1) * int(batch_size / 2)]
                        idx1_batch = I1[n * int(batch_size / 2):(n + 1) * int(batch_size / 2)]
                        idx = np.concatenate([idx0_batch, idx1_batch], axis=0)
                    elif strategy == 3:
                        idx = np.random.choice(list(range(Ptrain_tensor.shape[1])), size=int(batch_size), replace=False)
                        # idx = random_sample_8(ytrain, batch_size)   # to balance dataset

                    if dataset == 'P12' or dataset == 'P19' or dataset == 'eICU':
                        P, Ptime, Pstatic, y = Ptrain_tensor[:, idx, :].cuda(), Ptrain_time_tensor[:, idx].cuda(), \
                                               Ptrain_static_tensor[idx].cuda(), ytrain_tensor[idx].cuda()
                    elif dataset == 'PAMAP2':
                        P, Ptime, Pstatic, y = Ptrain_tensor[:, idx, :].cuda(), Ptrain_time_tensor[:, idx].cuda(), \
                                               None, ytrain_tensor[idx].cuda()

                    """Shape [128]. Length means the number of timepoints in each sample, for all samples in this batch"""
                    lengths = torch.sum(Ptime > 0, dim=0)

                    """Use two different ways to check the results' consistency"""
                    # outputs = model.forward(P, Pstatic, Ptime, lengths)
                    outputs = evaluate_standard(model, P, Ptime, Pstatic, static=static_info)

                    # if epoch == 0:
                    #     optimizer.zero_grad()
                    #     loss = criterion(outputs, y)
                    # elif epoch>0:  # Don't train the model at epoch==0

                    optimizer.zero_grad()
                    loss = criterion(outputs, y)
                    loss.backward()
                    optimizer.step()

                """Training performance"""
                if dataset == 'P12' or dataset == 'P19' or dataset == 'eICU':
                    train_probs = torch.squeeze(torch.sigmoid(outputs))
                    train_probs = train_probs.cpu().detach().numpy()
                    train_y = y.cpu().detach().numpy()
                    train_auroc = roc_auc_score(train_y, train_probs[:, 1])
                    train_auprc = average_precision_score(train_y, train_probs[:, 1])
                elif dataset == 'PAMAP2':
                    train_probs = torch.squeeze(nn.functional.softmax(outputs, dim=1))
                    # train_probs = torch.squeeze(torch.sigmoid(outputs))
                    train_probs = train_probs.cpu().detach().numpy()
                    train_y = y.cpu().detach().numpy()
                    train_auroc = roc_auc_score(one_hot(train_y), train_probs)
                    train_auprc = average_precision_score(one_hot(train_y), train_probs)

                # print("Train: Epoch %d, train loss:%.4f, train_auprc: %.2f, train_auroc: %.2f" % (
                #         epoch, loss.item(),  train_auprc * 100, train_auroc * 100))
                if wandb:
                    wandb.log({ "train_loss": loss.item(), "train_auprc": train_auprc, "train_auroc": train_auroc})
                # if epoch == 0 or epoch == num_epochs-1:
                #     print(confusion_matrix(train_y, np.argmax(train_probs, axis=1), labels=list(range(n_classes))))
                    # train_auc_val = roc_auc_score(y, probs[:, 1])
                    # train_aupr_val = average_precision_score(y, probs[:, 1])


                """Use the last """
                """Validation"""
                model.eval()
                if epoch ==0 or epoch % 1 == 0:
                    with torch.no_grad():
                        out_val = evaluate_standard(model, Pval_tensor, Pval_time_tensor, Pval_static_tensor, static=static_info)
                        out_val = torch.squeeze(torch.sigmoid(out_val))
                        out_val = out_val.detach().cpu().numpy()

                        # denoms = np.sum(np.exp(out_val), axis=1).reshape((-1, 1))
                        # probs = np.exp(out_val) / denoms
                        # ypred = np.argmax(out_val, axis=1)

                        val_loss = criterion(torch.from_numpy(out_val), torch.from_numpy(yval.squeeze(1)).long())

                        if dataset == 'P12' or dataset == 'P19' or dataset == 'eICU':
                            auc_val = roc_auc_score(yval, out_val[:, 1])
                            aupr_val = average_precision_score(yval, out_val[:, 1])
                        elif dataset == 'PAMAP2':
                            auc_val = roc_auc_score(one_hot(yval), out_val)
                            aupr_val = average_precision_score(one_hot(yval), out_val)

                        print("Validation: Epoch %d,  val_loss:%.4f, aupr_val: %.2f, auc_val: %.2f" % (epoch,
                          val_loss.item(), aupr_val * 100, auc_val * 100))
                        # print(confusion_matrix(yval, np.argmax(out_val, axis=1),))

                        if wandb:
                            wandb.log({ "val_loss": val_loss.item(), "val_auprc": aupr_val, "val_auroc": auc_val})

                        scheduler.step(aupr_val)
                        # save model
                        # if aupr_val > best_aupr_val:
                        #     best_aupr_val = aupr_val
                        if auc_val > best_auc_val:
                            best_auc_val = auc_val
                            print(
                                "**[S] Epoch %d, aupr_val: %.4f, auc_val: %.4f **" % (epoch, aupr_val * 100, auc_val * 100))
                            torch.save(model.state_dict(), model_path + arch + '_' + str(split_idx) + '.pt')

                # if epoch == 3:
                #     end = time.time()
                #     time_elapsed = end - start
                #     print('-- Estimated train time: %.3f mins --' % (time_elapsed / 60.0 / 4 * num_epochs))

            end = time.time()
            time_elapsed = end - start
            print('Total Time elapsed: %.3f mins' % (time_elapsed / 60.0))

            """testing"""
            model.load_state_dict(torch.load(model_path + arch + '_' + str(split_idx) + '.pt'))
            model.eval()

            with torch.no_grad():
                out_test = evaluate(model, Ptest_tensor, Ptest_time_tensor, Ptest_static_tensor, n_classes=n_classes, static=static_info).numpy()
                ypred = np.argmax(out_test, axis=1)

                denoms = np.sum(np.exp(out_test), axis=1).reshape((-1, 1))
                probs = np.exp(out_test) / denoms

                # auc = roc_auc_score(ytest, probs[:, 1])
                # aupr = average_precision_score(ytest, probs[:, 1])
                acc = np.sum(ytest.ravel() == ypred.ravel()) / ytest.shape[0]

                if dataset == 'P12' or dataset == 'P19' or dataset == 'eICU':
                    auc = roc_auc_score(ytest, probs[:, 1])
                    aupr = average_precision_score(ytest, probs[:, 1])
                elif dataset == 'PAMAP2':
                    auc = roc_auc_score(one_hot(ytest), probs)
                    aupr = average_precision_score(one_hot(ytest), probs)
                    precision = precision_score(ytest, ypred, average='macro', labels=np.unique(ypred))
                    recall = recall_score(ytest, ypred, average='macro', labels=np.unique(ypred))
                    F1 = f1_score(ytest, ypred, average='macro', labels=np.unique(ypred))
                    print('Testing: Precision = %.2f | Recall = %.2f | F1 = %.2f' % (precision * 100, recall * 100, F1 * 100))

                print('Testing: AUROC = %.2f | AUPRC = %.2f | Accuracy = %.2f' % (auc * 100, aupr * 100, acc * 100))
                print('classification report', classification_report(ytest, ypred))
                print(confusion_matrix(ytest, ypred, labels=list(range(n_classes))))

            # store
            acc_arr[k, m] = acc * 100
            auprc_arr[k, m] = aupr * 100
            auroc_arr[k, m] = auc * 100
            if dataset == 'PAMAP2':
                precision_arr[k, m] = precision * 100
                recall_arr[k, m] = recall * 100
                F1_arr[k, m] = F1 * 100

    # pick best performer for each split based on max AUPRC
    idx_max = np.argmax(auprc_arr, axis=1)
    acc_vec = [acc_arr[k, idx_max[k]] for k in range(n_splits)]
    auprc_vec = [auprc_arr[k, idx_max[k]] for k in range(n_splits)]
    auroc_vec = [auroc_arr[k, idx_max[k]] for k in range(n_splits)]
    if dataset == 'PAMAP2':
        precision_vec = [precision_arr[k, idx_max[k]] for k in range(n_splits)]
        recall_vec = [recall_arr[k, idx_max[k]] for k in range(n_splits)]
        F1_vec = [F1_arr[k, idx_max[k]] for k in range(n_splits)]

    print("missing ratio:{}, split type:{}, reverse:{}, using baseline:{}".format(missing_ratio, split, reverse, baseline))

    # display mean and standard deviation
    mean_acc, std_acc = np.mean(acc_vec), np.std(acc_vec)
    mean_auprc, std_auprc = np.mean(auprc_vec), np.std(auprc_vec)
    mean_auroc, std_auroc = np.mean(auroc_vec), np.std(auroc_vec)
    print('------------------------------------------')
    print('Accuracy = %.1f +/- %.1f' % (mean_acc, std_acc))
    print('AUPRC    = %.1f +/- %.1f' % (mean_auprc, std_auprc))
    print('AUROC    = %.1f +/- %.1f' % (mean_auroc, std_auroc))
    if dataset == 'PAMAP2':
        mean_precision, std_precision = np.mean(precision_vec), np.std(precision_vec)
        mean_recall, std_recall = np.mean(recall_vec), np.std(recall_vec)
        mean_F1, std_F1 = np.mean(F1_vec), np.std(F1_vec)
        print('Precision = %.1f +/- %.1f' % (mean_precision, std_precision))
        print('Recall    = %.1f +/- %.1f' % (mean_recall, std_recall))
        print('F1        = %.1f +/- %.1f' % (mean_F1, std_F1))


    # Mark the run as finished
    if wandb:
        wandb.finish()

    # # save in numpy file
    # np.save('./results/' + arch + '_phy12_setfunction.npy', [acc_vec, auprc_vec, auroc_vec])


