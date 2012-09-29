'''config.py - 
'''
import os
import time
import model

# start for tesing only
import json

# end for testing only

class Config(model.Model):
	def __init__(self, source):
		self._source = source
		self._config = {}
		self.__mtime = time.time()
	
	def _mod(self):
		self.__mtime = time.time()

	def _get_key(self, key):
		if key in self.config:
			return self._config[key]
		else:
			return None

	def get(self, *args, **kwargs):
		return_dict = {}
		if 'key' in kwargs:
			return self._get_key(kwargs['key'])
		elif len(kwargs) < 1:
			return self._config
		else:
			for key in args:
				return_dict[key] = self._get_key(key)
		self._mod()
		return return_dict

	def _set_key_value(self, key, value):
		self._config[key] = value
		return True

	def set(self, **kwargs):
		return_dict = {}
		if len(kwargs) == 1:
			return self._set_key_value(kwargs.keys()[0], kwargs.values()[0])
		else:
			for key, val in kwargs.items():
				return_dict[key] = self._set_key_value(key, val)
		self._mod()
		return return_dict

	def remove(self, *args):
		self._mod()
		return True

	def save(self):
		sink_file = open(self._source, 'w')
		json.dump(self._config, sink_file)
		sink_file.close()
		self._mod()
		return True

	def _load(self):
		source_file = open(self._source, 'r')
		config = json.load(source_file)
		source_file.close()
		return config

	def load(self):
		self._config = self._load()
		self._mod()
		return True

	def sync(self):
		source = self._load()
		mtime = os.stat(self._source).st_mtime
		if mtime > self.__mtime:
			self._config.update(source)
		else:
			source.update(self._config)
			self._config = source
		self._mod()
		return True

