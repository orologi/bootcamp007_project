import gc
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error
from sklearn.cross_validation import KFold
from scipy.stats import skew, boxcox
from sklearn.preprocessing import StandardScaler
from sklearn import preprocessing
import itertools

shift = 200
COMB_FEATURE = 'cat80,cat87,cat57,cat12,cat79,cat10,cat7,cat89,cat2,cat72,cat81,cat11,cat1,cat13,cat9,cat3,' \
               'cat16,cat90,cat23,cat36,cat73,cat103,cat40,cat28,cat111,cat6,cat76,cat50,cat5,cat4,cat14,cat38,' \
               'cat24,cat82,cat25'.split(',')

print("tAll")

def encode(charcode):
    r = 0
    if(type(charcode) is float):
        return np.nan
    else:
        ln = len(charcode)
        for i in range(ln):
            r += (ord(charcode[i]) - ord('A') + 1) * 26 ** (ln - i - 1)
        return r


def logregobj(preds, dtrain):
    labels = dtrain.get_label()
    con = 2
    x = preds - labels
    grad = con * x / (np.abs(x) + con)
    hess = con ** 2 / (np.abs(x) + con) ** 2
    return grad, hess


def xg_eval_mae(yhat, dtrain):
    y = dtrain.get_label()
    return 'mae', mean_absolute_error(np.exp(y) - shift,
                                      np.exp(yhat) - shift)


def mungeskewed(train, test, numeric_feats):
    ntrain = train.shape[0]
    test['loss'] = 0
    train_test = pd.concat((train, test)).reset_index(drop=True)
    # compute skew and do Box-Cox transformation (Tilli)
    skewed_feats = train[numeric_feats].apply(lambda x: skew(x.dropna()))
    print("\nSkew in numeric features:")
    print(skewed_feats)
    skewed_feats = skewed_feats[skewed_feats > 0.25]
    skewed_feats = skewed_feats.index

    for feats in skewed_feats:
        train_test[feats] = train_test[feats] + 1
        train_test[feats], lam = boxcox(train_test[feats])
    return train_test, ntrain


if __name__ == "__main__":
    print('Started')
    # directory = '../input/'
    train = pd.read_csv('./noproc_6to4/train.csv')
    test = pd.read_csv('./noproc_6to4/test.csv')
    submission = pd.read_csv('./noproc_6to4/sample_submission_64.csv')

    numeric_feats = [x for x in train.columns[1:-1] if 'cont' in x]
    cats = [x for x in train.columns[1:-1] if 'cat' in x]
    train_test, ntrain = mungeskewed(train, test, numeric_feats)

    # taken from Vladimir's script (https://www.kaggle.com/iglovikov/allstate-claims-severity/xgb-1114)
    for column in list(train.select_dtypes(include=['object']).columns):
        if train[column].nunique() != test[column].nunique():
            set_train = set(train[column].unique())
            set_test = set(test[column].unique())
            remove_train = set_train - set_test
            remove_test = set_test - set_train

            remove = remove_train.union(remove_test)


            def filter_cat(x):
                if x in remove:
                    return np.nan
                return x


            train_test[column] = train_test[column].apply(lambda x: filter_cat(x), 1)

    # taken from Ali's script (https://www.kaggle.com/aliajouz/allstate-claims-severity/singel-model-lb-1117)
    train_test["cont1"] = np.sqrt(preprocessing.minmax_scale(train_test["cont1"]))
    train_test["cont4"] = np.sqrt(preprocessing.minmax_scale(train_test["cont4"]))
    train_test["cont5"] = np.sqrt(preprocessing.minmax_scale(train_test["cont5"]))
    train_test["cont8"] = np.sqrt(preprocessing.minmax_scale(train_test["cont8"]))
    train_test["cont10"] = np.sqrt(preprocessing.minmax_scale(train_test["cont10"]))
    train_test["cont11"] = np.sqrt(preprocessing.minmax_scale(train_test["cont11"]))
    train_test["cont12"] = np.sqrt(preprocessing.minmax_scale(train_test["cont12"]))

    train_test["cont6"] = np.log(preprocessing.minmax_scale(train_test["cont6"]) + 0000.1)
    train_test["cont7"] = np.log(preprocessing.minmax_scale(train_test["cont7"]) + 0000.1)
    train_test["cont9"] = np.log(preprocessing.minmax_scale(train_test["cont9"]) + 0000.1)
    train_test["cont13"] = np.log(preprocessing.minmax_scale(train_test["cont13"]) + 0000.1)
    train_test["cont14"] = (np.maximum(train_test["cont14"] - 0.179722, 0) / 0.665122) ** 0.25


    for comb in itertools.combinations(COMB_FEATURE, 2):
        feat = comb[0] + "_" + comb[1]
        train_test[feat] = train_test[comb[0]] + train_test[comb[1]]
        train_test[feat] = train_test[feat].apply(encode)
        print(feat)

    cats = [x for x in train.columns[1:-1] if 'cat' in x]
    for col in cats:
        train_test[col] = train_test[col].apply(encode)
    train_test.loss = np.log(train_test.loss + shift)
    ss = StandardScaler()
    train_test[numeric_feats] = \
        ss.fit_transform(train_test[numeric_feats].values)
    train = train_test.iloc[:ntrain, :].copy()
    test = train_test.iloc[ntrain:, :].copy()
    test.drop('loss', inplace=True, axis=1)

    print pd.DataFrame(test).shape
    pd.DataFrame(test).to_csv("proc3_test.csv", index=False)




    print('Median Loss:', train.loss.median())
    print('Mean Loss:', train.loss.mean())
    xgb_params = {
        'seed': 0,
        'colsample_bytree': 0.7,
        'silent': 1,
        'subsample': 0.7,
        'learning_rate': 0.03,
        'objective': 'reg:linear',
        'max_depth': 12,
        'min_child_weight': 100,
        'booster': 'gbtree',
    }


    best_nrounds = 20000  # 640 score from above commented out code (Faron)
    allpredictions = pd.DataFrame()
    kfolds = 10  # 10 folds is better!
    if kfolds > 1:
        kf = KFold(train.shape[0], n_folds=kfolds)
        for i, (train_index, test_index) in enumerate(kf):
            dtest = xgb.DMatrix(test[test.columns[1:]])
            print('Fold {0}'.format(i + 1))
            X_train, X_val = train.iloc[train_index], train.iloc[test_index]
            cols_ = [x for x in X_train.columns if 'loss' not in x][1:]
            dtrain = \
                xgb.DMatrix(X_train[cols_],
                            label=X_train.loss)
            dvalid = \
                xgb.DMatrix(X_val[cols_],
                            label=X_val.loss)
            watchlist = [(dtrain, 'train'), (dvalid, 'eval')]

            gbdt = xgb.train(xgb_params, dtrain, best_nrounds, watchlist,
                             obj=logregobj,
                             feval=xg_eval_mae, maximize=False,
                             verbose_eval=50,
                             early_stopping_rounds=25)
            del dtrain
            del dvalid
            gc.collect()
            allpredictions['p' + str(i)] = \
                gbdt.predict(dtest, ntree_limit=gbdt.best_ntree_limit)
            del dtest
            del gbdt
            gc.collect()
    else:
        cols_ = [x for x in train.columns if 'loss' not in x][1:]

        dtest = xgb.DMatrix(test[cols_].values)
        dtrain = \
            xgb.DMatrix(train[cols_].values,
                        label=train.loss)
        watchlist = [(dtrain, 'train'), (dtrain, 'eval')]
        gbdt = xgb.train(xgb_params, dtrain, best_nrounds, watchlist,
                         obj=logregobj,
                         feval=xg_eval_mae, maximize=False,
                         verbose_eval=50, early_stopping_rounds=25)
        allpredictions['p1'] = \
            gbdt.predict(dtest, ntree_limit=gbdt.best_ntree_limit)
        del dtrain
        del dtest
        del gbdt
        gc.collect()

    print(allpredictions.head())

    if (kfolds > 1):
        submission.iloc[:, 1] = \
            np.exp(allpredictions.mean(axis=1).values) - shift
        submission.to_csv('proc3o_XGB_64_t.csv', index=None)
        # submission.iloc[:, 1] = \
        #     np.exp(allpredictions.median(axis=1).values) - shift
        # submission.to_csv('xgbmediansubmission.csv', index=None)
    else:
        submission.iloc[:, 1] = np.exp(allpredictions.p1.values) - shift
        submission.to_csv('proc3o_XGB_64_t.csv', index=None)
    print('Finished')
