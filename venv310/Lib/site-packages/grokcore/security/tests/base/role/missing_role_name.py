"""
A role has to have a name to be defined.

  >>> grokcore.security.testing.grok(__name__)
  Traceback (most recent call last):
  martian.error.GrokError: A role needs to have a dotted name for its id. \
  Use grok.name to specify one.
"""

import grokcore.security
import grokcore.security.testing


class MissingName(grokcore.security.Role):
    pass
