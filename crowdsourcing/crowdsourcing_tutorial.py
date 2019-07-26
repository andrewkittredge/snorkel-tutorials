# %% [markdown]
# # Crowdsourcing tutorial
# In this tutorial, we'll provide a simple walkthrough of how to use Snorkel to resolve conflicts
# in a noisy, hybrid dataset for a sentiment analysis task.
# We have crowdsourced labels for a portion of the training dataset, and combine these
# with heuristic labeling functions to increase the number of training labels we have.
# Like most Snorkel labeling pipelines, we'll use the denoised labels to train a deep learning
# model which can be applied to new, unseen data to automatically make predictions!
#
# In this tutorial, we're using the
# [Weather Sentiment](https://data.world/crowdflower/weather-sentiment)
# dataset from Figure Eight.
# Our goal is to label each tweet as either positive or negative so that
# we can train a language model over the tweets themselves that can be applied
# to new, unseen data points.
# Crowd workers were asked to grade the sentiment of a
# particular tweet relating to the weather.
# Crowd workers could choose among the following categories:
#
# * Positive
# * Negative
# * I can't tell
# * Neutral / author is just sharing information
# * Tweet not related to weather condition
#
# The catch is that 20 crowd workers graded each tweet, and in many cases
# crowd workers assigned conflicting sentiment labels to the same tweet.
# This is a common issue when dealing with crowdsourced labeling workloads.
#
# We've also altered the data set to reflect a realistic crowdsourcing pipeline
# where only a subset of our full training set have recieved crowd labels.
# We'll encode the crowd labels themselves as labeling functions in order
# to learn trust weights for each crowd worker, and write a few heuristic
# labeling functions to cover the data points without crowd labels.
# Snorkel's ability to build high-quality datasets from multiple noisy labeling
# signals makes it an ideal framework to approach this problem.

# %% [markdown]
# We start by loading our data which has 287 examples in total.
# We take 50 for our development set and 50 for our test set.
# The remaining 187 examples form our training set.
# This data set is very small, and we're primarily using it for demonstration purposes.
# In particular, we'd expect to have access to many more unlabeled tweets in order to
# train a high performance text model.
#
# The labels above have been mapped to integers, which we show here.

# %% [markdown]
# ## Loading Crowdsourcing Dataset

# %%
import os

if os.path.basename(os.getcwd()) == "snorkel-tutorials":
    os.chdir("crowdsourcing")

# %%
from data import load_data, answer_mapping

crowd_answers, df_train, df_dev, df_test = load_data()
Y_dev = df_dev.sentiment.values
Y_test = df_test.sentiment.values

print("Answer to int mapping:")
for k, v in sorted(answer_mapping.items(), key=lambda kv: kv[1]):
    print(f"{k:<50}{v}")

# %% [markdown]
# First, let's take a look at our development set to get a sense of
# what the tweets look like.

# %%
df_dev.head()

# %% [markdown]
# Now let's take a look at the crowd labels.
# We'll convert these into labeling functions.

# %%
crowd_answers.head()

# %% [markdown]
# ## Writing Labeling Functions
# Each crowd worker can be thought of as a single labeling function,
# as each worker labels a subset of examples,
# and may have errors or conflicting answers with other workers / labeling functions.
# So we create one labeling function per worker.
# We'll simply return the label the worker submitted for a given tweet, and abstain
# if they didn't submit an answer for it.

# %% [markdown]
# ### Crowd worker labeling functions

# %%
labels_by_annotator = crowd_answers.groupby("worker_id")
worker_dicts = {}
for worker_id in labels_by_annotator.groups:
    worker_df = labels_by_annotator.get_group(worker_id)[["answer"]]
    if len(worker_df) > 10:
        worker_dicts[worker_id] = dict(zip(worker_df.index, worker_df.answer))

print("Number of workers:", len(worker_dicts))

# %%
from snorkel.labeling.lf import LabelingFunction


def f_pos(x, worker_dict):
    label = worker_dict.get(x.tweet_id)
    return 1 if label == 1 else -1


def f_neg(x, worker_dict):
    label = worker_dict.get(x.tweet_id)
    return 0 if label == 0 else -1


def get_worker_labeling_function(worker_id, f):
    worker_dict = worker_dicts[worker_id]
    name = f"worker_{worker_id}"
    return LabelingFunction(name, f=f, resources={"worker_dict": worker_dict})


worker_lfs_pos = [
    get_worker_labeling_function(worker_id, f_pos) for worker_id in worker_dicts
]
worker_lfs_neg = [
    get_worker_labeling_function(worker_id, f_neg) for worker_id in worker_dicts
]

# %% [markdown]
# Let's take a quick look at how well they do on the development set.

# %%
from snorkel.labeling.apply import PandasLFApplier

lfs = worker_lfs_pos + worker_lfs_neg

applier = PandasLFApplier(lfs)
L_train = applier.apply(df_train)
L_dev = applier.apply(df_dev)

# %%
from snorkel.labeling.analysis import LFAnalysis

LFAnalysis(L_dev, lfs).lf_summary(Y_dev).head(10)

# %% [markdown]
# So the crowd labels are quite good! But how much of our dev and training
# sets do they cover?

# %%
print("Training set coverge:", LFAnalysis(L_train).label_coverage())
print("Dev set coverge:", LFAnalysis(L_dev).label_coverage())

# %% [markdown]
# ### Additional labeling functions
#
# We can mix the crowd worker labeling functions with labeling
# functions of other types.
# We'll use a few varied approaches and use the label model learn
# how to combine their values.

# %%
from snorkel.labeling.lf import labeling_function
from snorkel.labeling.preprocess import preprocessor
from textblob import TextBlob


@preprocessor()
def textblob_polarity(x):
    scores = TextBlob(x.tweet_text)
    x.polarity = scores.polarity
    return x


textblob_polarity.memoize = True


@labeling_function(preprocessors=[textblob_polarity])
def polarity_positive(x):
    return 1 if x.polarity > 0.3 else -1


@labeling_function(preprocessors=[textblob_polarity])
def polarity_negative(x):
    return 0 if x.polarity < -0.25 else -1


@labeling_function(preprocessors=[textblob_polarity])
def polarity_negative_2(x):
    return 0 if x.polarity <= 0.3 else -1


# %% [markdown]
# ### Applying labeling functions to the training set

# %%
from snorkel.labeling.apply import PandasLFApplier

text_lfs = [polarity_positive, polarity_negative, polarity_negative_2]
lfs = text_lfs + worker_lfs_pos + worker_lfs_neg

applier = PandasLFApplier(lfs)
L_train = applier.apply(df_train)
L_dev = applier.apply(df_dev)

# %%
LFAnalysis(L_dev, lfs).lf_summary(Y_dev).head(10)

# %% [markdown]
# Using the text-based LFs, we've expanded coverage on both our training set
# and dev set to 100%.
# We'll now take these noisy and conflicting labels, and use the label model
# to denoise and combine them.

# %%
print("Training set coverge:", LFAnalysis(L_train).label_coverage())
print("Dev set coverge:", LFAnalysis(L_dev).label_coverage())

# %% [markdown]
# ## Train Label Model And Generate Soft Labels

# %%
from snorkel.labeling.model.label_model import LabelModel

# Train label model.
label_model = LabelModel(cardinality=2, verbose=True)
label_model.fit(L_train, n_epochs=100, seed=123, log_freq=20, l2=0.1, lr=0.01)

# %% [markdown]
# As a spot-check for the quality of our label model, we'll score it on the dev set.

# %%
from snorkel.analysis.metrics import metric_score
from snorkel.analysis.utils import probs_to_preds

Y_dev_prob = label_model.predict_proba(L_dev)
Y_dev_pred = probs_to_preds(Y_dev_prob)

acc = metric_score(Y_dev, Y_dev_pred, probs=None, metric="accuracy")
print(f"Label Model Accuracy: {acc:.3f}")

# %% [markdown]
# Look at that, we get very high accuracy on the development set.
# This is due to the abundance of high quality crowd worker labels.
# **Since we don't have these high quality crowdsourcing labels for the
# test set or new incoming examples, we can't use the label model reliably
# at inference time.**
# In order to run inference on new incoming examples, we need to train a
# discriminative model over the tweets themselves.
# Let's generate a set of probabilistic labels for the training set.

# %%
Y_train_prob = label_model.predict_proba(L_train)

# %% [markdown]
# ## Use Soft Labels to Train End Model

# %% [markdown]
# ### Getting features from BERT
# Since we have very limited training data, we cannot train a complex model like an LSTM with a lot of parameters. Instead, we use a pre-trained model, [BERT](https://github.com/google-research/bert), to generate embeddings for each our tweets, and treat the embedding values as features.

# %%
import numpy as np
import torch
from pytorch_transformers import BertModel, BertTokenizer

model = BertModel.from_pretrained("bert-base-uncased")
tokenizer = BertTokenizer.from_pretrained("bert-base-uncased")


def encode_text(text):
    input_ids = torch.tensor([tokenizer.encode(text)])
    return model(input_ids)[0].mean(1)[0].detach().numpy()


train_vectors = np.array(list(df_train.tweet_text.apply(encode_text).values))
test_vectors = np.array(list(df_test.tweet_text.apply(encode_text).values))

# %% [markdown]
# ### Model on soft labels
# Now, we train a simple logistic regression model on the BERT features, using labels
# obtained from our label model.

# %%
from sklearn.linear_model import LogisticRegression

sklearn_model = LogisticRegression(solver="liblinear")
sklearn_model.fit(train_vectors, probs_to_preds(Y_train_prob))

print(f"Accuracy of trained model: {sklearn_model.score(test_vectors, Y_test)}")