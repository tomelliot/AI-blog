# OpenGym Seaquest-v0
# -------------------
#
# This code demonstrates a Double DQN network with Priority Experience Replay
# in an OpenGym Seaquest-v0 environment.
#
# Made as part of blog series Let's make a DQN, available at:
# https://jaromiru.com/2016/11/07/lets-make-a-dqn-double-learning-and-prioritized-experience-replay/
#
# author: Jaromir Janisch, 2016

import random, numpy, math, gym, scipy
from . import SumTree
from tensorflow.keras import backend as K
import tensorflow as tf


IMAGE_WIDTH = 11
IMAGE_HEIGHT = 11
IMAGE_STACK = 1

HUBER_LOSS_DELTA = 2.0
LEARNING_RATE = 0.00025

#-------------------- UTILITIES -----------------------
def huber_loss(y_true, y_pred):
    err = y_true - y_pred

    cond = K.abs(err) < HUBER_LOSS_DELTA
    L2 = 0.5 * K.square(err)
    L1 = HUBER_LOSS_DELTA * (K.abs(err) - 0.5 * HUBER_LOSS_DELTA)

    loss = tf.where(cond, L2, L1)   # Keras does not cover where function in tensorflow :-(

    return K.mean(loss)

def processImage( img ):
    # rgb = scipy.misc.imresize(img, (IMAGE_WIDTH, IMAGE_HEIGHT), interp='bilinear')
    #
    # r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    # gray = 0.2989 * r + 0.5870 * g + 0.1140 * b     # extract luminance
    #
    # o = gray.astype('float32') / 128 - 1    # normalize
    # return o
    return img

#-------------------- BRAIN ---------------------------
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import *
from tensorflow.keras.optimizers import *

class Brain:
    def __init__(self, stateCnt, actionCnt):
        self.stateCnt = stateCnt
        self.actionCnt = actionCnt

        self.model = self._createModel()
        self.model_ = self._createModel()  # target network

    def _createModel(self):
        model = Sequential()

        model.add(Conv2D(16, (3, 3), strides=(4,4), activation='relu', input_shape=(11,11,1), data_format='channels_last'))
        model.add(Flatten())
        model.add(Dense(units=512, activation='relu'))

        model.add(Dense(units=self.actionCnt, activation='linear'))

        opt = RMSprop(lr=LEARNING_RATE)
        model.compile(loss=huber_loss, optimizer=opt)

        return model

    def train(self, x, y, epochs=1, verbose=0):
        self.model.fit(x, y, batch_size=32, epochs=epochs, verbose=verbose)

    def predict(self, s, target=False):
        if target:
            return self.model_.predict(s)
        else:
            return self.model.predict(s)

    def predictOne(self, s, target=False):
        return self.predict(s.reshape(1, IMAGE_WIDTH, IMAGE_HEIGHT, IMAGE_STACK), target).flatten()

    def updateTargetModel(self):
        self.model_.set_weights(self.model.get_weights())

#-------------------- MEMORY --------------------------
class Memory:   # stored as ( s, a, r, s_ ) in SumTree
    e = 0.01
    a = 0.6

    def __init__(self, capacity):
        self.tree = SumTree.SumTree(capacity)

    def _getPriority(self, error):
        return (error + self.e) ** self.a

    def add(self, error, sample):
        p = self._getPriority(error)
        self.tree.add(p, sample)

    def sample(self, n):
        batch = []
        segment = self.tree.total() / n

        for i in range(n):
            a = segment * i
            b = segment * (i + 1)

            s = random.uniform(a, b)
            (idx, p, data) = self.tree.get(s)
            batch.append( (idx, data) )

        return batch

    def update(self, idx, error):
        p = self._getPriority(error)
        self.tree.update(idx, p)

#-------------------- AGENT ---------------------------
MEMORY_CAPACITY = 200000

BATCH_SIZE = 1

GAMMA = 0.99

MAX_EPSILON = 1
MIN_EPSILON = 0.1

EXPLORATION_STOP = 500000   # at this step epsilon will be 0.01
LAMBDA = - math.log(0.01) / EXPLORATION_STOP  # speed of decay

UPDATE_TARGET_FREQUENCY = 10000

class Agent:
    steps = 0
    epsilon = MAX_EPSILON

    def __init__(self, stateCnt, actionCnt, verbose=False):
        self.stateCnt = stateCnt
        self.actionCnt = actionCnt
        self.verbose = verbose

        self.brain = Brain(stateCnt, actionCnt)
        # self.memory = Memory(MEMORY_CAPACITY)

    def act(self, s):
        if random.random() < self.epsilon:
            return random.randint(0, self.actionCnt-1)
        else:
            return numpy.argmax(self.brain.predictOne(s))

    def observe(self, sample):  # in (s, a, r, s_) format
        x, y, errors = self._getTargets([(0, sample)])
        self.memory.add(errors[0], sample)

        if self.steps % UPDATE_TARGET_FREQUENCY == 0:
            self.brain.updateTargetModel()

        # slowly decrease Epsilon based on our eperience
        self.steps += 1
        self.epsilon = MIN_EPSILON + (MAX_EPSILON - MIN_EPSILON) * math.exp(-LAMBDA * self.steps)

    def extract_states(self, batch):
        no_state = numpy.zeros(self.stateCnt)

        states = numpy.array([ o[1][0] for o in batch ])
        states_ = numpy.array([ (no_state if o[1][3] is None else o[1][3]) for o in batch ])

        states = states[..., numpy.newaxis]
        states_ = states_[..., numpy.newaxis]
        return states, states_

    def getPredictions(self, states, states_):
            p = self.brain.predict(states)

            p_ = self.brain.predict(states_, target=False)
            pTarget_ = self.brain.predict(states_, target=True)
            return p, p_, pTarget_

    def getStateAndPrediction(self, batch, p, pTarget_, p_):
        o = batch[1]
        s = o[0]; a = o[1]; r = o[2]; s_ = o[3]
        s = s[..., numpy.newaxis]

        t = p
        oldVal = t[a]
        if s_ is None:
            t[a] = r
        else:
            t[a] = r + GAMMA * pTarget_[ numpy.argmax(p_) ]  # double DQN

        x = s
        y = t
        errors = abs(oldVal - t[a])
        return x, y, errors


    def _getTargets(self, batch):
        states, states_ = self.extract_states(batch)
        if self.verbose:
            print("states.shape:  {}".format(states.shape))
            print("states_.shape:  {}".format(states_.shape))

        if (states_.ndim < 3) or (states.ndim < 3):
            import ipdb; ipdb.set_trace()
        try:
            p, p_, pTarget_ = self.getPredictions(states, states_)
        except Exception as e:
            print(e)
            import ipdb
            ipdb.set_trace()

        x = numpy.zeros((len(batch), IMAGE_WIDTH, IMAGE_HEIGHT, IMAGE_STACK))
        y = numpy.zeros((len(batch), self.actionCnt))
        errors = numpy.zeros(len(batch))

        for i in range(len(batch)):
            x[i], y[i], errors[i] = self.getStateAndPrediction(batch[i], p[i], pTarget_[i], p_[i])

        return (x, y, errors)

    def replay(self):
        batch = self.memory.sample(BATCH_SIZE)
        x, y, errors = self._getTargets(batch)

        #update errors
        for i in range(len(batch)):
            idx = batch[i][0]
            self.memory.update(idx, errors[i])

        self.brain.train(x, y)

class RandomAgent:
    memory = Memory(MEMORY_CAPACITY)
    exp = 0

    def __init__(self, actionCnt):
        self.actionCnt = actionCnt

    def act(self, s):
        return random.randint(0, self.actionCnt-1)

    def observe(self, sample):  # in (s, a, r, s_) format
        error = abs(sample[2])  # reward
        self.memory.add(error, sample)
        self.exp += 1

    def replay(self):
        pass

#-------------------- ENVIRONMENT ---------------------
class Environment:
    def __init__(self, problem):
        self.problem = problem
        self.env = gym.make(problem)

    def run(self, agent):
        img = self.env.reset()
        w = processImage(img)
        s = numpy.array([w, w])

        R = 0
        while True:
            # self.env.render()
            a = agent.act(s)

            r = 0
            img, r, done, info = self.env.step(a)
            s_ = numpy.array([s[1], processImage(img)]) #last two screens

            r = np.clip(r, -1, 1)   # clip reward to [-1, 1]

            if done: # terminal state
                s_ = None

            agent.observe( (s, a, r, s_) )
            agent.replay()

            s = s_
            R += r

            if done:
                break

        print("Total reward:", R)
