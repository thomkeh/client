import pytest
from click.testing import CliRunner
import os
import json
import tensorflow as tf
from tensorflow.keras.models import Sequential, Model
from tensorflow.keras.layers import Flatten, Dense, Reshape, Embedding, Input, LSTM, Concatenate
from tensorflow.keras import backend as K
import wandb
from wandb import wandb_run
from wandb.keras import WandbCallback

import sys
import glob

# Tests which rely on row history in memory should set `History.keep_rows = True`
from wandb.history import History
History.keep_rows = True


@pytest.fixture
def dummy_model(request):
    K.clear_session()
    multi = request.node.get_closest_marker('multiclass')
    image_output = request.node.get_closest_marker('image_output')
    if multi:
        nodes = 10
        loss = 'categorical_crossentropy'
    else:
        nodes = 1
        loss = 'binary_crossentropy'
    nodes = 1 if not multi else 10
    if image_output:
        nodes = 300
    model = Sequential()
    model.add(Flatten(input_shape=(10, 10, 3)))
    model.add(Dense(nodes, activation='sigmoid'))
    if image_output:
        model.add(Dense(nodes, activation="relu"))
        model.add(Reshape((10, 10, 3)))
    model.compile(optimizer='adam',
                  loss=loss,
                  metrics=['accuracy'])
    return model


@pytest.fixture
def dummy_data(request):
    multi = request.node.get_closest_marker('multiclass')
    image_output = request.node.get_closest_marker('image_output')
    cats = 10 if multi else 1
    import numpy as np
    data = np.random.randint(255, size=(100, 10, 10, 3))
    labels = np.random.randint(2, size=(100, cats))
    if image_output:
        labels = data
    return (data, labels)


def test_basic_keras(dummy_model, dummy_data, wandb_init_run):
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36,
                    callbacks=[WandbCallback()])
    wandb.run.summary.load()
    assert wandb.run.history.rows[0]["epoch"] == 0
    assert wandb.run.summary["loss"] > 0
    assert len(wandb.run.summary["graph"].nodes) == 3


def test_keras_image_bad_data(dummy_model, dummy_data, wandb_init_run):
    error = False
    data, labels = dummy_data

    try:
        dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=(data.reshape(10), labels),
                        callbacks=[WandbCallback(data_type="image")])
    except ValueError:
        error = True
    assert error


def test_keras_image_binary(dummy_model, dummy_data, wandb_init_run):
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=dummy_data,
                    callbacks=[WandbCallback(data_type="image")])
    assert len(wandb.run.history.rows[0]["examples"]['captions']) == 36


def test_keras_image_binary_captions(dummy_model, dummy_data, wandb_init_run):
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=dummy_data,
                    callbacks=[WandbCallback(data_type="image", predictions=10, labels=["Rad", "Nice"])])
    assert wandb.run.history.rows[0]["examples"]['captions'][0] in [
        "Rad", "Nice"]


@pytest.mark.multiclass
def test_keras_image_multiclass(dummy_model, dummy_data, wandb_init_run):
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=dummy_data,
                    callbacks=[WandbCallback(data_type="image", predictions=10)])
    assert len(wandb_init_run.history.rows[0]["examples"]['captions']) == 10


@pytest.mark.multiclass
def test_keras_image_multiclass_captions(dummy_model, dummy_data, wandb_init_run):
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=dummy_data,
                    callbacks=[WandbCallback(data_type="image", predictions=10, labels=["Rad", "Nice", "Fun", "Rad", "Nice", "Fun", "Rad", "Nice", "Fun", "Rad"])])
    assert wandb_init_run.history.rows[0]["examples"]['captions'][0] in [
        "Rad", "Nice", "Fun"]


@pytest.mark.image_output
def test_keras_image_output(dummy_model, dummy_data, wandb_init_run):
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=dummy_data,
                    callbacks=[WandbCallback(data_type="image", predictions=10)])
    assert wandb_init_run.history.rows[0]["examples"]['count'] == 30
    assert wandb_init_run.history.rows[0]["examples"]['grouping'] == 3


def test_dataset_functional(wandb_init_run):
    data = tf.data.Dataset.range(5).map(lambda x: (x, 1)).batch(1)
    inputs = tf.keras.Input(shape=(1,))
    outputs = tf.keras.layers.Dense(1)(inputs)
    wandb_callback = WandbCallback(save_model=False)

    model = tf.keras.Model(inputs=inputs, outputs=outputs)
    model.compile(optimizer=tf.keras.optimizers.Adam(), loss='mse')
    model.fit(data, callbacks=[wandb_callback])
    assert wandb.data_types.Graph.to_json(wandb_init_run.summary["graph"])['nodes'][0]['class_name'] == "InputLayer"

def test_keras_log_weights(dummy_model, dummy_data, wandb_init_run):
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=dummy_data,
                    callbacks=[WandbCallback(data_type="image", log_weights=True)])
    assert wandb_init_run.history.rows[0]['parameters/dense.weights']['_type'] == "histogram"


def test_keras_save_model(dummy_model, dummy_data, wandb_init_run):
    dummy_model.fit(*dummy_data, epochs=2, batch_size=36, validation_data=dummy_data,
                    callbacks=[WandbCallback(data_type="image", save_model=True)])
    assert len(glob.glob(wandb_init_run.dir + "/model-best.h5")) == 1


def test_keras_convert_sequential():
    # necessary to keep the names of the layers consistent
    K.clear_session()

    model = Sequential()
    model.add(Dense(4, input_shape=(3,)))
    model.add(Dense(5))
    model.add(Dense(6))
    wandb_model = wandb.data_types.Graph.from_keras(model)
    wandb_model_out = wandb.Graph.to_json(wandb_model)
    print(wandb_model_out)
    assert wandb_model_out == {'_type': 'graph', 'format': 'keras',
                               'nodes': [
                                   {'name': 'dense_input', 'id': 'dense_input', 'class_name': 'InputLayer', 'output_shape': [
                                       (None, 3)], 'num_parameters': 0},
                                   {'name': 'dense', 'id': 'dense', 'class_name': 'Dense', 'output_shape': (
                                       None, 4), 'num_parameters': 16},
                                   {'name': 'dense_1', 'id': 'dense_1', 'class_name': 'Dense', 'output_shape': (
                                       None, 5), 'num_parameters': 25},
                                   {'name': 'dense_2', 'id': 'dense_2', 'class_name': 'Dense', 'output_shape': (None, 6), 'num_parameters': 36}],
                               'edges': [['dense_input', 'dense'], ['dense', 'dense_1'], ['dense_1', 'dense_2']]}


def test_keras_convert_model_non_sequential():
    # necessary to keep the names of the layers consistent
    K.clear_session()

    # example from the Keras docs
    main_input = Input(shape=(100,), dtype='int32', name='main_input')
    x = Embedding(output_dim=512, input_dim=10000,
                  input_length=100)(main_input)
    lstm_out = LSTM(32)(x)
    auxiliary_output = Dense(1, activation='sigmoid',
                             name='aux_output')(lstm_out)
    auxiliary_input = Input(shape=(5,), name='aux_input')
    x = Concatenate()([lstm_out, auxiliary_input])
    x = Dense(64, activation='relu')(x)
    x = Dense(64, activation='relu')(x)
    x = Dense(64, activation='relu')(x)
    main_output = Dense(1, activation='sigmoid', name='main_output')(x)
    model = Model(inputs=[main_input, auxiliary_input],
                  outputs=[main_output, auxiliary_output])
    wandb_model = wandb.data_types.Graph.from_keras(model)
    wandb_model_out = wandb.Graph.to_json(wandb_model)

    print(wandb_model_out['edges'])
    assert wandb_model_out['nodes'][0] == {'name': 'main_input', 'id': 'main_input',
                                           'class_name': 'InputLayer', 'output_shape': [(None, 100)], 'num_parameters': 0}
    assert wandb_model_out['edges'] == [['main_input', 'embedding'], ['embedding', 'lstm'], ['lstm', 'concatenate'], ['aux_input', 'concatenate'], [
        'concatenate', 'dense'], ['dense', 'dense_1'], ['dense_1', 'dense_2'], ['dense_2', 'main_output'], ['lstm', 'aux_output']]
