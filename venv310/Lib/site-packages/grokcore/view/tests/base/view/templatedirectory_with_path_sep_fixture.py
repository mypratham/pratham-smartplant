"""
This should fail because you can not use path separator in templatedir
directive.
"""
import os.path

import grokcore.view as grok


grok.templatedir('templatedirectoryname' + os.path.sep + 'subdirname')
