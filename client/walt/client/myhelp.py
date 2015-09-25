import sys

def register_topic(topic, message):
    message_per_topic[topic] = message
    message_per_topic['help'] = \
        'Available help topics are:\n%s' % \
        ', '.join(sorted(t for t in message_per_topic if t != 'help'))

def get(topic):
    if topic not in message_per_topic:
        print 'No such help topic.'
        return get('help')
    return message_per_topic[topic]

message_per_topic = {}

