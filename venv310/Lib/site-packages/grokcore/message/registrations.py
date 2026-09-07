"""Register a global message receiver and a global session based
message source.
"""
import grokcore.component as grok
import z3c.flashmessage


grok.global_utility(z3c.flashmessage.receiver.GlobalMessageReceiver)
grok.global_utility(z3c.flashmessage.sources.SessionMessageSource,
                    name='session')
