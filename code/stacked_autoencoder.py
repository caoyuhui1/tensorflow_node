# -*- coding: utf-8 -*-

import numpy as np
import random
import tensorflow as tf
from tensorflow.python.client import timeline

from utils import SummaryWriter
from utils.logger import log

allowed_activations = ['sigmoid', 'tanh', 'softmax', 'relu', 'linear']
allowed_noises = [None, 'gaussian', 'mask']
allowed_losses = ['rmse', 'cross-entropy']

class StackedAutoEncoder:
    """
    A deep autoencoder with denoising capability
    based on https://github.com/rajarsheem/libsdae 
    extended for standalone use in DeSTIN perception framework
    """



    def __init__(self, dims, activations, encoding_activations=None, decoding_activations=None, name='ae', epoch=100, noise=None, loss='rmse', lr=0.001, metadata=False, timeline=False):
        # object initialization
        self.name = name+'-%08x' % random.getrandbits(32)
        self.session = tf.Session()
        self.iteration = 0 # one iteration is fitting batch_size*epoch times.
        self.last_activation = None # stores the transformation performed last.
        # parameters
        self.lr = lr
        self.loss = loss
        
        self.encoding_activations = activations
        self.decoding_activations = activations

        if (encoding_activations != None):
            self.encoding_activations = encoding_activations

        if (decoding_activations != None):
            self.decoding_activations = decoding_activations

        self.noise = noise
        self.epoch = epoch
        self.dims = dims
        self.metadata = metadata # collect metadata information
        self.timeline = timeline # collect timeline information
        self.assertions()
        # namescope for summary writers
        with tf.name_scope(self.name) as scope:
            self.scope = scope
            with tf.name_scope("transform") as transform_scope:
                self.transform_scope = transform_scope
        # layer variables and ops
        self.depth = len(dims)
        self.layers = []
        for i in xrange(self.depth):
            self.layers.append({'encode_weights': None, 
                                'encode_biases': None, 
                                'decode_biases': None, 
                                'run_op': None, 
                                'summ_op': None, 
                                'encode_op': None, 
                                'decode_op': None})

        # callback to other autoencoders, triggered when transform called.
        self.callbacks = []
        self.input_buffer = {}


        log.info("👌 Autoencoder initalized " + self.name)

    def __del__(self):
        self.session.close()
        log.info("🖐 Autoencoder " + self.name + " deallocated, closed session.")




    # fit given data and return transformed
    def fit_transform(self, x):
        log.debug(self.name+": received shape " + str(x.shape))
        self.fit(x)
        return self.transform(x)

    # fit given data
    def fit(self, x):
        # increase iteration counter
        self.iteration += 1

        for i in range(self.depth):
            log.info(self.name + ' layer {0}'.format(i + 1)+' iteration {0}'.format(self.iteration))

            #if this is the first iteration initialize the graph
            if (self.iteration == 1):
                self.init_run(input_dim=len(x[0]),
                              layer=i,
                              hidden_dim=self.dims[i], 
                              encoding_activation=self.encoding_activations[i], 
                              decoding_activation=self.decoding_activations[i], 
                              loss=self.loss, 
                              lr=self.lr)

            if self.noise is None:
                x = self.run(data_x=x, 
                             data_x_=x,
                             layer=i,
                             epoch=self.epoch[i])
            else:
                temp = np.copy(x)
                x = self.run(data_x=self.add_noise(temp),
                             data_x_=x,
                             layer=i,
                             epoch=self.epoch[i])

    def transform(self, data):
        sess = self.session

        with tf.name_scope(self.scope):
            with tf.name_scope(self.transform_scope):
                x = tf.constant(data, dtype=tf.float32)
                for layer, a in zip(self.layers, self.encoding_activations):
                    layer = tf.matmul(x, layer['encode_weights']) + layer['encode_biases']
                    x = self.activate(layer, a)
        
        # make the calculation
        transformed = x.eval(session=sess)
        self.last_activation = transformed
        self.emit_callbacks(transformed)

        return transformed

    # main run call to fit data for given layer
    def run(self, data_x, data_x_, layer, epoch):
        sess = self.session

        if self.metadata:
            run_options = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
            run_metadata = tf.RunMetadata()
        else:
            run_options = None
            run_metadata = None

        feeding_scope = self.name+"/layer_"+str(layer)+"/input/"

        # fit the model according to number of epochs:
        for i in range(epoch):
            feed_dict = {feeding_scope+'x:0':  data_x, feeding_scope+'x_:0': data_x_}
            sess.run(self.layers[layer]['run_op'], feed_dict=feed_dict, options=run_options, run_metadata=run_metadata)
            

        # create the timeline object, and write it to a json
        if self.metadata and self.timeline:
            tl = timeline.Timeline(run_metadata.step_stats)
            ctf = tl.generate_chrome_trace_format()
            with open(SummaryWriter().get_output_folder('timelines')+"/"+self.name+"_layer_"+str(layer)+"_iteration_"+str(self.iteration)+".json", 'w') as f:
                f.write(ctf)
                log.info("📊 written timeline trace.")

        # put metadata into summaries.
        if self.metadata:
            SummaryWriter().writer.add_run_metadata(run_metadata, self.name+'_layer'+str(layer)+'_step%d' % (self.iteration*epoch + i))

        # run summary operation.
        summary_str = sess.run(self.layers[layer]['summ_op'], feed_dict=feed_dict, options=run_options, run_metadata=run_metadata)
        SummaryWriter().writer.add_summary(summary_str, self.iteration*epoch + i)
        SummaryWriter().writer.flush()

        return sess.run(self.layers[layer]['encode_op'], feed_dict={feeding_scope+'x:0': data_x_})


    # initialize variables according to params and input data for given layer.
    def init_run(self, input_dim, hidden_dim, encoding_activation, decoding_activation, loss, lr, layer):
        sess = self.session

        # store all variables, so that we can later determinate what new variables there are
        temp = set(tf.all_variables())

        # get absolute scope
        with tf.name_scope(self.scope):
            with tf.name_scope("layer_"+str(layer)):
                # input placeholders            
                with tf.name_scope('input'):
                    x = tf.placeholder(dtype=tf.float32, shape=[None, input_dim], name='x')
                    x_ = tf.placeholder(dtype=tf.float32, shape=[None, input_dim], name='x_')
    
                # weight and bias variables
                with tf.variable_scope(self.name):
                    with tf.variable_scope("layer_"+str(layer)):
                        encode_weights = tf.get_variable("encode_weights", (input_dim, hidden_dim), initializer=tf.random_normal_initializer())
                        decode_weights = tf.transpose(encode_weights)
                        encode_biases = tf.get_variable("encode_biases", (hidden_dim), initializer=tf.random_normal_initializer())
                        decode_biases = tf.get_variable("decode_biases", (input_dim), initializer=tf.random_normal_initializer())

                with tf.name_scope("encoded"):
                    encoded = self.activate(tf.matmul(x, encode_weights) + encode_biases, encoding_activation, label="encoded")

                with tf.name_scope("decoded"):
                    decoded = self.activate(tf.matmul(encoded, decode_weights) + decode_biases, decoding_activation, label="decoded")

                with tf.name_scope("loss"):
                    # reconstruction loss
                    if loss == 'rmse':
                        loss = tf.sqrt(tf.reduce_mean(tf.square(tf.sub(x_, decoded))))
                    elif loss == 'cross-entropy':
                        #loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(decoded, x_))  ### TODO this is not working in it's current form! why?
                        loss = -tf.reduce_mean(x_ * tf.log(decoded))
                    # record loss
                
                with tf.name_scope("train"):
                    train_op = tf.train.AdamOptimizer(lr).minimize(loss)

                # Add summary ops to collect data
                summary_key = self.name+"_layer_"+str(layer);

                tf.histogram_summary(self.name+"_encode_weights_layer_"+str(layer), encode_weights, collections=[summary_key])
                tf.histogram_summary(self.name+"_encode_biases_layer_"+str(layer), encode_biases, collections=[summary_key])
                tf.histogram_summary(self.name+"_decode_weights_layer_"+str(layer), decode_weights, collections=[summary_key])
                tf.histogram_summary(self.name+"_decode_biases_layer_"+str(layer), decode_biases, collections=[summary_key])
                tf.scalar_summary(self.name+"_loss_layer_"+str(layer), loss, collections=[summary_key])
                
                # Merge all summaries into a single operator
                merged_summary_op = tf.merge_all_summaries(key=summary_key)             
                
                # initialize summary writer with graph 
                SummaryWriter().writer.add_graph(sess.graph)

                # initalize all new variables
                sess.run(tf.initialize_variables(set(tf.all_variables()) - temp))
        
                # initalize accessor variables
                self.layers[layer]['encode_weights'] = encode_weights
                self.layers[layer]['encode_biases'] = encode_biases
                self.layers[layer]['decode_biases'] = decode_biases

                self.layers[layer]['encode_op'] = encoded
                self.layers[layer]['decode_op'] = decoded
                
                self.layers[layer]['run_op'] = train_op
                self.layers[layer]['summ_op'] = merged_summary_op





    # register for data from another autoencoder.
    def register_for_ae(self, ae):
        if (self.iteration > 0):
            #TODO: allow this at some point
            log.warning("Can't register for new data, already run!")
        else:
            log.debug(self.name + " registering for input from " + ae.name)
            #create slot for data
            self.input_buffer[ae.name] = None
            #register for callback with other AE
            ae.callbacks.append(self.receive_data_from)

    # register for data from an input layer
    def register_for_inputlayer(self, inputlayer, region):
        if (self.iteration > 0):
            #TODO: allow this at some point
            log.warning("Can't register for new data, already run!")
        else:
            log.debug(self.name + " registering for input from an inputlayer")
            inputlayer.register_callback(region, self.fit_transform)

    # receive data from other autoencoder or input layer and store in buffer
    def receive_data_from(self, from_name, data):
        if not from_name in self.input_buffer:
            log.warning(self.name + " can't receive data from "+from_name+", it's not registered.")
            return
        #check if buffer is full:
        if (isinstance(self.input_buffer[from_name], np.ndarray)):
            log.warning(self.name + " can't receive data from "+from_name+", buffer full- still waiting for the other AEs")
            return

        ##all set!
        log.debug("succesfully received data from " + from_name)
        self.input_buffer[from_name] = data
        self.check_input_buffer()

    # check if input_buffer is full and if yes, execute transform and trigger our callbacks.
    def check_input_buffer(self):
        # check if all buffers are valid arrays.
        if all(isinstance(item, np.ndarray) for item in self.input_buffer.values()):
            log.debug("input buffer complete, executing fit_transform and triggering callbacks...")

            # concatenate data and execute fit_transform
            data = self.input_buffer.values()          
            batch_size = data[0].shape[0]
            data = np.concatenate(tuple(data), axis=1)
            
            # transform!
            self.fit_transform(data)
    
            #clear buffer
            for key in self.input_buffer:
                self.input_buffer[key] = None

    def emit_callbacks(self, data):
        # trigger registered callbacks
        for callback in self.callbacks:
            callback(self.name, data)




    # save parameters to disk using tf.train.Saver
    def save_parameters(self):
        sess = self.session

        to_be_saved = {}

        for layer in xrange(self.depth):
            to_be_saved['layer'+str(layer)+'_encode_weights'] = self.layers[layer]['encode_weights']
            to_be_saved['layer'+str(layer)+'_encode_biases'] = self.layers[layer]['encode_biases']
            to_be_saved['layer'+str(layer)+'_decode_biases'] = self.layers[layer]['decode_biases']

        saver = tf.train.Saver(to_be_saved)
        saver.save(sess, SummaryWriter().get_output_folder('checkpoints')+"/"+self.name+"_"+str(self.iteration))

        log.info("💾 model saved.")

    def load_parameters(self, filename):
        raise NotImplementedError()
        #TODO
        #self.saver.restore(sess, ....)
        #log.info("💾✅ model restored.")





    # visualization of maximum activation for all hidden neurons on layer 0
    # according to: http://deeplearning.stanford.edu/wiki/index.php/Visualizing_a_Trained_Autoencoder)
    def max_activation_summary(self):
        sess = self.session

        #layer 0 not initialized.
        if (self.layers[0]['encode_weights'] == None):
            return

        W = self.layers[0]['encode_weights'].eval(session=sess)

        input_wh = int(np.ceil(np.power(W.shape[0],0.5)))
        input_shape = [input_wh, input_wh]

        ## note we floor the number of plotted outputs here, 
        # so we always plot an even number instead of padding.
        output_wh = int(np.floor(np.power(W.shape[1],0.5)))
        output_shape = [input_wh*output_wh, input_wh*output_wh]
        
        outputs = []
        output_rows = []

        activation_image = np.zeros(output_shape, dtype=np.float32)

        #calculate for each hidden neuron
        for i in xrange(W.shape[1]):
            output = np.array(np.zeros(input_wh*input_wh),dtype='float32')
        
            W_ij_sum = 0

            for j in xrange(W.shape[0]):
                W_ij_sum += np.power(W[j][i],2)
        
            for j in xrange(W.shape[0]):
                W_ij = W[j][i]
                output[j] = (W_ij)/(np.sqrt(W_ij_sum))

            outputs.append(output.reshape(input_shape))

        for i in xrange(output_wh):
            output_rows.append(np.concatenate(outputs[i*output_wh:(i*output_wh)+output_wh], 0))

        activation_image = np.concatenate(output_rows, 1)
        
        image_summary_op = tf.image_summary("max_activation_"+self.name, np.reshape(activation_image, (1, output_shape[0], output_shape[1], 1)))
        image_summary_str = sess.run(image_summary_op)
        
        SummaryWriter().writer.add_summary(image_summary_str, self.iteration)
        SummaryWriter().writer.flush()

        log.info("📈 activation image plotted.")

    # plot visualization of last activation batch to summary
    def transformed_summary(self):
        sess = self.session

        activation_wh = int(np.ceil(np.power(self.last_activation.shape[1],0.5)))
        data_shape = [activation_wh, activation_wh]

        output_wh = int(np.floor(np.power(self.last_activation.shape[0],0.5)))

        output_rows = []
        outputs = []

        for activation in self.last_activation:
            outputs.append(activation.reshape(data_shape))

        for i in xrange(output_wh):
            output_rows.append(np.concatenate(outputs[i*output_wh:(i*output_wh)+output_wh], 0))

        activation_image = np.concatenate(output_rows, 1)

        image_summary_op = tf.image_summary("transformed_"+self.name, np.reshape(activation_image, (1, data_shape[0]*output_wh, data_shape[1]*output_wh, 1)))
        image_summary_str = sess.run(image_summary_op)
        
        SummaryWriter().writer.add_summary(image_summary_str, self.iteration)
        SummaryWriter().writer.flush()

        log.info("📈 transformed input image plotted.")



    # noise for denoising AE.
    def add_noise(self, x):
        if self.noise == 'gaussian':
            n = np.random.normal(0, 0.2, (len(x), len(x[0]))).astype(x.dtype)
            return x + n
        if 'mask' in self.noise:
            frac = float(self.noise.split('-')[1])
            temp = np.copy(x)
            for i in temp:
                n = np.random.choice(len(i), int(round(frac * len(i))), replace=False)
                i[n] = 0
            return temp
        if self.noise == 'sp':
            pass

    # different activation functions
    def activate(self, linear, name, label='encoded'):
        if name == 'sigmoid':
            return tf.nn.sigmoid(linear, name=label)
        elif name == 'softmax':
            return tf.nn.softmax(linear, name=label)
        elif name == 'linear':
            return linear
        elif name == 'tanh':
            return tf.nn.tanh(linear, name=label)
        elif name == 'relu':
            return tf.nn.relu(linear, name=label)





    # sanity checks
    def assertions(self):
        global allowed_activations, allowed_noises, allowed_losses
        assert self.loss in allowed_losses, 'Incorrect loss given'
        assert 'list' in str(
            type(self.dims)), 'dims must be a list even if there is one layer.'
        assert len(self.epoch) == len(
            self.dims), "No. of epochs must equal to no. of hidden layers"
        #assert len(self.activations) == len(
        #    self.dims), "No. of activations must equal to no. of hidden layers"
        assert all(
            True if x > 0 else False
            for x in self.epoch), "No. of epoch must be atleast 1"
        #assert set(self.activations + allowed_activations) == set(
        #    allowed_activations), "Incorrect activation given."
        assert self.noise_validator(
            self.noise, allowed_noises), "Incorrect noise given"

    def noise_validator(self, noise, allowed_noises):
        '''Validates the noise provided'''
        try:
            if noise in allowed_noises:
                return True
            elif noise.split('-')[0] == 'mask' and float(noise.split('-')[1]):
                t = float(noise.split('-')[1])
                if t >= 0.0 and t <= 1.0:
                    return True
                else:
                    return False
        except:
            return False
        pass

