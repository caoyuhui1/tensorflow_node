# -*- coding: utf-8 -*-

class InputLayer:
    """
    Contains the worker thread that uses OpenCV to feed in images and video feeds to TF.
    """
    
    def assertions(self):
        assert(42==42)
    
    def __init__(self):
        self.assertions()
        self.callbacks = []
        print ("📸 Input Layer initalized")

    def registerCallback(self, region, callback):
        ##assert callback is a function
        self.callbacks.append([region, callback])
        print ("📸 callback registered")


    def deregisterCallback(self, callback):
        raise NotImplementedError()
