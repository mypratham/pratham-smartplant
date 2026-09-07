import grokcore.component as grok

import grokcore.security


class NotAPermissionSubclass:
    grok.name('not really a permission')


class MyRole:
    grokcore.security.permissions(NotAPermissionSubclass)
