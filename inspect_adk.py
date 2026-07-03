import importlib, inspect, json, sys
import google.adk as adk
print('adk module file:', adk.__file__)
print('adk version:', getattr(adk, '__version__', 'N/A'))
from google.adk.apps import App
print('App class methods:', [m for m in dir(App) if not m.startswith('_')])
