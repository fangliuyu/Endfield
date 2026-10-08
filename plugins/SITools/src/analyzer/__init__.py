#!/usr/bin/env python
# -*- coding: utf-8 -*-

from os.path import dirname, basename, isfile
import glob
import logging

# Import all scopes
modules = glob.glob(dirname(__file__) + "/*.py")
__all__ = [basename(f)[:-3] for f in modules if isfile(f) and not f.endswith('__init__.py')]
logging.debug(f"[Frame Init] Importing all the following modules :\n %s", __all__)
