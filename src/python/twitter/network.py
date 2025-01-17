import json
import keras
import keras.preprocessing.text as kpt
import nltk
import numpy as np
import os
import pandas as pd
import psycopg2
import re
import seaborn as sns
import sklearn
import sys
import tqdm

from keras.layers import Acivation, Dense, Dropout
from keras.models import modle_from_json, Sequential
from nltk.corpus import stopwords, wordnet
from nltk.tokenize import word_tokenize
from postgres_credentials import *
from pycorenlp import StanfordCoreMLP
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.preprocessing import Normalizer
from sqlalchemy import create_engine
from wordcloud import WordCloud

"""
Visualizing Twitter followers to analyze the public opinion of a keyword input.
Usage: `python keyword image` for some keyword to search Twitter for and an image
file to use as a mask for the word cloud.

This script runs the entire shindig from querying Twitter, preprocessing the obtained text,
visualizing the data, preparing the data for the neural network, training the neural network
on the data, testing it, and figuring out which model is the most accurate in predicting new
tweets. 
"""

# Get the user input.
kw = sys.argv[1] # keyword
if len(sys.argv) == 2:
    mi = None
elif len(sys.argv) == 3:
    mi = sys.argv[2] 

def base(tabletweets):
    """
    Query the databse from a table of tweets. 
    """
    engine = create_engine("postgresql+psycopg2://%s:%s@%s:%d/%s" %(usertwitter, passwordtwitter, hosttwitter, porttwitter, dbnametwitter))
    table = pd.read_sql_query("select * from %s" %tabletweets,con=engine, index_col="id")
    return table

def preprocessing_text(table):
    """
    Preprocess the tweets by putting them in an easy-to-understand format. 
    This means getting rid of links, blanks, etc.
    """
    # Put everything in lowercase.
    table["tweet"] = table["tweet"].str.lower()
    # Replace rt indicating that was a retweet.
    table["tweet"] = table["tweet"].str.replace("rt", "")
    # Replace occurences of mentioning @UserNames.
    table["tweet"] = table["tweet"].replace(r"@\w+", "", regex=True)
    # Replace links contained in the tweet.
    table["tweet"] = table["tweet"].replace(r'http\S+', "", regex=True)
    table["tweet"] = table["tweet"].replace(r'www.[^ ]+', "", regex=True)
    # Remove numbers.
    table["tweet"] = table["tweet"].replace(r'[0-9]+', "", regex=True)
    # Replace special characters and puntuation marks.
    table["tweet"] = table["tweet"].replace(r'[!"#$%&()*+,-./:;<=>?@[\]^_`{|}~]', "", regex=True)
    return table

def indict(word):
    """
    Keep the words that are based off other words as the base words they're
    made off of.
    """
    if wordnet.synsets(word):
        # If the word is in the dictionary, we'll return True.
        return True

def replace_elongated_word(word):
    regex = r'(\w*)(\w+)\2(\w*)'
    repl = r'\1\2\3'    
    if indict(word):
        return word
    new_word = re.sub(regex, repl, word)
    if new_word != word:
        return replace_elongated_word(new_word)
    else:
        return new_word

def detect_elongated_words(row):
    """
    Find the long ones.
    """
    regexrep = r'(\w*)(\w+)(\2)(\w*)'
    words = ["".join(i) for i in re.findall(regexrep, row)]
    for word in words:
        if not indict(word):
            row = re.sub(word, replace_elongated_word(word), row)
    return row


def stop_words(table):
    """
    We need to remove the stop words. These are the prepositions, small words, etc., that
    don't give us more info.
    """
    stop_words_list = stopwords.words("english")
    table["tweet"] = table["tweet"].str.lower()
    table["tweet"] = table["tweet"].apply(lambda x: " ".join([word for word in x.split() if word not in (stop_words_list)]))
    return table

def replace_antonyms(word):
    """
    We get all the lemma for the word.
    """
    for syn in wordnet.synsets(word): 
        for lemma in syn.lemmas(): 
            #if the lemma is an antonyms of the word
            if lemma.antonyms(): 
                #we return the antonym
                return lemma.antonyms()[0].name()
    return word
            
def handling_negation(row):
    """
    Tokenize the row.
    """
    words = word_tokenize(row)
    speach_tags = ["JJ", "JJR", "JJS", "NN", "VB", "VBD", "VBG", "VBN", "VBP"]
    #We obtain the type of words that we have in the text, we use the pos_tag function
    tags = nltk.pos_tag(words)
    #Now we ask if we found a negation in the words
    tags_2 = ""
    if "n't" in words and "not" in words:
        tags_2 = tags[min(words.index("n't"), words.index("not")):]
        words_2 = words[min(words.index("n't"), words.index("not")):]
        words = words[:(min(words.index("n't"), words.index("not")))+1]
    elif "n't" in words:
        tags_2 = tags[words.index("n't"):]
        words_2 = words[words.index("n't"):] 
        words = words[:words.index("n't")+1]
    elif "not" in words:
        tags_2 = tags[words.index("not"):]
        words_2 = words[words.index("not"):]
        words = words[:words.index("not")+1] 
    for index, word_tag in enumerate(tags_2):
        if word_tag[1] in speach_tags:
            words = words+[replace_antonyms(word_tag[0])]+words_2[index+2:]
            break
    return " ".join(words)

def cleantable(table):
    """
    This function will process all the required cleaning for the text in our tweets.
    """
    table = preprocessing_text(table)
    table["tweet"] = table["tweet"].apply(lambda x: detect_elongated_words(x))
    table["tweet"] = table["tweet"].apply(lambda x: handling_negation(x))
    table = stop_words(table)
    return table

def vectorization(table):
    """
    Vectorize the table into a format that can be visualized.
    This lets pandas and matplotlib create visuals that can be stretched
    and fitted.
    """
    # CountVectorizer will convert a collection of text documents to a matrix of token counts.
    # Produces a sparse representation of the counts.
    # Initialize.
    vector = CountVectorizer()
    # We fit and transform the vector created.
    frequency_matrix = vector.fit_transform(table.tweet)
    # Sum all the frequencies for each word.
    sum_frequencies = np.sum(frequency_matrix, axis=0)
    # Now we use squeeze to remove single-dimensional entries 
    # from the shape of an array that we got from applying 
    # np.asarray to the sum of frequencies.
    frequency = np.squeeze(np.asarray(sum_frequencies))
    # Now we get into a dataframe all the frequencies 
    # and the words that they correspond to.
    frequency_df = pd.DataFrame([frequency], columns=vector.get_feature_names()).transpose()
    return frequency_df

def word_cloud(tweets, maskimage):
    """
    Create the word cloud for input tweets and a maskimage image file of a shape
    or picture on which to display the wordcloud.
    """
    # We read the mask image into a numpy array.
    if maskimage:
        wordmask = np.array(Image.open(os.path.join(os.getcwd(), maskimage)))
    else:
        wordmask = None 
    # Now we store the tweets into a series to be able to process.
    # tweets_list = pd.Series([t for t in tweet_table.tweet]).str.cat(sep=" ") 
    # We generate the wordcloud using the series created and the mask.
    wc = WordCloud(width=2000, height=1000, max_font_size=200, background_color="black", max_words=2000, mask=wordmask, contour_width=1, 
                           contour_color="steelblue", colormap="nipy_spectral", stopwords=[kw])
    wc.generate(tweets)
    # wordcloud = WordCloud(width=1600, height=800,max_font_size=200).generate(tweets_list)
    # Now we plot both figures, the wordcloud and the mask
    plt.figure(figsize=(10,10))
    plt.imshow(wc, interpolation="hermite")
    plt.axis("off")
    # plt.imshow(wordmask, cmap=plt.cm.gray, interpolation="bilinear")
    # plt.axis("off")    
    plt.show()

def wfgraph(wf, sent):
    """
    Create a network graph of word frequency wf.
    """
    labels = wf[0][1:51].index
    title = ("Word Frequency for %s" %sent)
    # Plot.
    plt.figure(figsize=(10,5))
    plt.bar(np.arange(50), wf[0][1:51], width = 0.8, color = sns.color_palette("bwr"), alpha=0.5, 
            edgecolor = "black", capsize=8, linewidth=1)
    plt.xticks(np.arange(50), labels, rotation=90, size=14)
    plt.xlabel("50 more frequent words", size=14)
    plt.ylabel("Frequency", size=14)
    # plt.title(("Word Frequency for %s", size=18) % sent)
    plt.title(title, size=18)
    plt.grid(False)
    plt.gca().spines["top"].set_visible(False)
    plt.gca().spines["right"].set_visible(False)
    plt.show()


def regression_graph(table):
    """
    Use regression to graph the table and separate it into the 
    underlying factors that cause the tweets and data.
    """
    table = table[1:]
    # Plot.
    sns.set_style("whitegrid")   
    plt.figure(figsize=(6,6))
    points = plt.scatter(table["Positive"], table["Negative"], c=table["Positive"], s=75, cmap="bwr")
    plt.colorbar(points)
    sns.regplot(x="Positive", y="Negative",fit_reg=False, scatter=False, color=".1", data=table)
    plt.xlabel("Frequency for Positive Tweets", size=14)
    plt.ylabel("Frequency for Negative Tweets", size=14)
    plt.title("Word frequency in Positive vs. Negative Tweets", size=14)
    plt.grid(False)
    sns.despine()

def splitting(table):
    """
    Split the data into training and test datasets.
    """
    X_train, X_test, y_train, y_test = train_test_split(table.tweet, table.sentiment, test_size=0.2, shuffle=True)
    return X_train, X_test, y_train, y_test

def tokenization_tweets(dataset, features):
    """
    Tokenize the tweets into an easy-to-read format.
    """
    tokenization = TfidfVectorizer(max_features=features)
    tokenization.fit(dataset)
    dataset_transformed = tokenization.transform(dataset).toarray()
    return dataset_transformed

def train(X_train_mod, y_train, features, shuffle, drop, layer1, layer2, epoch, lr, epsilon, validation):
    """
    Create and train the neural network.
    """
    model_nn = Sequential()
    model_nn.add(Dense(layer1, input_shape=(features,), activation='relu'))
    model_nn.add(Dropout(drop))
    model_nn.add(Dense(layer2, activation='sigmoid'))
    model_nn.add(Dropout(drop))
    model_nn.add(Dense(3, activation='softmax'))
    
    optimizer = keras.optimizers.Adam(lr=lr, beta_1=0.9, beta_2=0.999, epsilon=epsilon, decay=0.0, amsgrad=False)
    model_nn.compile(loss="sparse_categorical_crossentropy",
                 optimizer=optimizer,
                 metrics=["accuracy"])
    model_nn.fit(np.array(X_train_mod), y_train,
                 batch_size=32,
                 epochs=epoch,
                 verbose=1,
                 validation_split=validation,
                 shuffle=shuffle)
    return model_nn

def test(X_test, model_nn):
    """
    Test the model.
    """
    prediction = model_nn.predict(X_test)
    return prediction

tabletweets = "tweets_" + kw # table name
tweet_table = querydb(tabletweets)
tweet_table = cleantable(tweet_table)

# Draw a word cloud.
word_cloud(pd.Series([t for t in tweet_table.tweet]).str.cat(sep=" "), mi) 
    
# For positive tweets 
word_cloud(pd.Series([t for t in tweet_table[tweet_table.sentiment == "Positive"].tweet]).str.cat(sep=" "), mi)   

# For negative tweets
word_cloud(pd.Series([t for t in tweet_table[tweet_table.sentiment == "Negative"].tweet]).str.cat(sep=" "), mi)

# Get the frequency.
word_frequency = vectorization(tweet_table).sort_values(0, ascending = False)
word_frequency_pos = vectorization(tweet_table[tweet_table["sentiment"] == "Positive"]).sort_values(0, ascending = False)
word_frequency_neg = vectorization(tweet_table[tweet_table["sentiment"] == "Negative"]).sort_values(0, ascending = False)

# Graph with frequency words all, positive 
# and negative tweets and get the frequency.
graph(word_frequency, "all")
graph(word_frequency_pos, "positive")
graph(word_frequency_neg, "negative")

# Concatenate word frequency for positive and negative.
table_regression = pd.concat([word_frequency_pos, word_frequency_neg], axis=1, sort=False)
table_regression.columns = ["Positive", "Negative"]
regression_graph(table_regression)

tabletweets = "tweets_" + kw + "_labeled"
tweet_table = querydb(tabletweets)
tweet_table["sentiment"] = tweet_table["sentiment"].apply(lambda x: 2 if x == "Positive" else (0 if x == "Negative" else 1))

X_train, X_test, y_train, y_test = splitting(tweet_table)

def model1(X_train, y_train):
    """
    Train our sequential neural network.
    """
    features = 3500
    shuffle = True
    drop = 0.5
    layer1 = 512
    layer2 = 256
    epoch = 5
    lr = 0.001
    epsilon = None
    validation = 0.1
    X_train_mod = tokenization_tweets(X_train, features)
    model = train(X_train_mod, y_train, features, shuffle, drop, layer1, layer2, epoch, lr, epsilon, validation)
    return model

def model2(X_train, y_train):   
    features = 3000
    shufle = True
    drop = 0.5
    layer1 = 512
    layer2 = 256
    epoch = 5
    lr = 0.001
    epsilon = None
    validation = 0.1
    X_train_mod = tokenization_tweets(X_train, features)
    model = train(X_train_mod, y_train, features, shufle, drop, layer1, layer2, epoch, lr, epsilon, validation)
    return model

def model3(X_train, y_train):   
    features = 3500
    shufle = True
    drop = 0.5
    layer1 = 512
    layer2 = 256
    epoch = 5
    lr = 0.002
    epsilon = None
    validation = 0.1
    X_train_mod = tokenization_tweets(X_train, features)
    model = train(X_train_mod, y_train, features, shufle, drop, layer1, layer2, epoch, lr, epsilon, validation)
    return model

def model4(X_train, y_train):   
    features = 5000
    shufle = True
    drop = 0.5
    layer1 = 512
    layer2 = 256
    epoch = 2
    lr = 0.005
    epsilon = None
    validation = 0.1
    X_train_mod = tokenization_tweets(X_train, features)
    model = train(X_train_mod, y_train, features, shufle, drop, layer1, layer2, epoch, lr, epsilon, validation)
    return model

def model5(X_train, y_train):   
    features = 3500
    shufle = True
    drop = 0.5
    layer1 = 512
    layer2 = 256
    epoch = 5
    lr = 0.002
    epsilon = 1e-5
    validation = 0.1
    X_train_mod = tokenization_tweets(X_train, features)
    model = train(X_train_mod, y_train, features, shufle, drop, layer1, layer2, epoch, lr, epsilon, validation)
    return model

def model6(X_train, y_train):   
    features = 3500
    shufle = True
    drop = 0.5
    layer1 = 512
    layer2 = 256
    epoch = 5
    lr = 0.002
    epsilon = 1e-8
    validation = 0.1
    X_train_mod = tokenization_tweets(X_train, features)
    model = train(X_train_mod, y_train, features, shufle, drop, layer1, layer2, epoch, lr, epsilon, validation)
    return model

def model7(X_train, y_train):   
    features = 3500
    shufle = True
    drop = 0.5
    layer1 = 512
    layer2 = 256
    epoch = 6
    lr = 0.002
    epsilon = 1e-8
    validation = 0.1
    X_train_mod = tokenization_tweets(X_train, features)
    model = train(X_train_mod, y_train, features, shufle, drop, layer1, layer2, epoch, lr, epsilon, validation)
    return model

def model8(X_train, y_train):   
    features = 3500
    shufle = True
    drop = 0.5
    layer1 = 512
    layer2 = 256
    epoch = 5
    lr = 0.002
    epsilon = 1e-9
    validation = 0.1
    X_train_mod = tokenization_tweets(X_train, features)
    model = train(X_train_mod, y_train, features, shufle, drop, layer1, layer2, epoch, lr, epsilon, validation)
    return model

def model9(X_train, y_train):   
    features = 3500
    shufle = False
    drop = 0.5
    layer1 = 512
    layer2 = 256
    epoch = 5
    lr = 0.002
    epsilon = 1e-9
    validation = 0.1
    X_train_mod = tokenization_tweets(X_train, features)
    model = train(X_train_mod, y_train, features, shufle, drop, layer1, layer2, epoch, lr, epsilon, validation)
    return model

def model10(X_train, y_train):   
    features = 3500
    shufle = True
    drop = 0.5
    layer1 = 512
    layer2 = 256
    epoch = 5
    lr = 0.002
    epsilon = 1e-9
    validation = 0.2
    X_train_mod = tokenization_tweets(X_train, features)
    model = train(X_train_mod, y_train, features, shufle, drop, layer1, layer2, epoch, lr, epsilon, validation)
    return model

def model11(X_train, y_train):   
    features = 3000
    shufle = True
    drop = 0.5
    layer1 = 512
    layer2 = 256
    epoch = 5
    lr = 0.002
    epsilon = 1e-9
    validation = 0.2
    X_train_mod = tokenization_tweets(X_train, features)
    model = train(X_train_mod, y_train, features, shufle, drop, layer1, layer2, epoch, lr, epsilon, validation)
    return model

def save_model(model):
    """
    Save the model as a json fie and an h5 (hierarchical data format).
    """
    model_json = model.to_json()
    with open("model.json", "w") as json_file:
        json_file.write(model_json)
    model.save_weights("model.h5")

# Test out each model to find the one with the greatest accuracy.
winner = model1 # winning model
winacc = model1(X_train, y_train).history["accuracy"] # winning accuracy
modellist = [model1,
             model2,
             model3,
             model4,
             model5,
             model6,
             model7,
             model8,
             model9,
             model10,
             model11]
for modelno in modellist:
    curracc = modelno(X_train, y_train).history["accuracy"] # currency model accuracy
    if curacc > winacc:
        winacc = curacc
        winner = modelno

print("The most accurate model is: " + str(winner))
save_model(winner)

# Predict Tweets based off the keyword.
tabletweetsnew = "tweets_predict_" + kw
tweet_table_new = querydb(tabletweetsnew)
tweet_table_new = cleantable(tweet_table_new)

X_new = tokenization_tweets(tweet_table_new.tweet, 3500)
new_prediction = winner.predict(X_new)

labels = ["Negative", "Neutral", "Positive"]
sentiments = [labels[np.argmax(pred)] for pred in new_prediction]
tweet_table_new["sentiment"] = sentiments

sizes = [sentiments.count("Negative"), sentiments.count("Neutral"), sentiments.count("Positive")]
explode = (0, 0, 0.1)
labels = "Negative", "Neutral", "Positive"
plt.figure(figsize=(5,5))
plt.pie(sizes, explode=explode, colors="bwr", labels=labels, autopct="%1.1f%%",
        shadow=True, startangle=90, wedgeprops={"alpha":0.8})
plt.axis("equal")
plt.show()

engine = create_engine("postgresql+psycopg2://%s:%s@%s:%d/%s" %(usertwitter, passwordtwitter, hosttwitter, porttwitter, dbnametwitter))
tweet_table_new.to_sql("tweets_" + kw + "_new_labeled", con=engine, if_exists="append")
