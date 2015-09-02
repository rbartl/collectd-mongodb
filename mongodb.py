#
# Plugin to collectd statistics from MongoDB
#

import collectd
import pymongo
from distutils.version import StrictVersion as V


class MongoDB(object):

    def __init__(self):
        self.plugin_name = "mongo"
        self.mongo_host = "127.0.0.1"
        self.mongo_port = 27017
        self.mongo_db = ["admin", ]
        self.mongo_user = None
        self.mongo_password = None
        self.mongo_monitoring_level = None

        self.lockTotalTime = None
        self.lockTime = None
        self.accesses = None
        self.misses = None

    def submit(self, type, instance, value, db=None):
        if db:
            plugin_instance = '%s-%s' % (self.mongo_port, db)
        else:
            plugin_instance = str(self.mongo_port)
        v = collectd.Values()
        v.plugin = self.plugin_name
        v.plugin_instance = plugin_instance
        v.type = type
        v.type_instance = instance
        v.values = [value, ]
        v.dispatch()

    def do_server_status(self):
        con = pymongo.MongoClient(self.mongo_host, self.mongo_port)
        db = con[self.mongo_db[0]]
        if self.mongo_user and self.mongo_password:
            db.authenticate(self.mongo_user, self.mongo_password)
        server_status = db.command('serverStatus')

        version = server_status['version']
        at_least_2_4 = V(version) >= V('2.4.0')
        eq_gt_3_0 = V(version) >= V('3.0.0')

        #uptime
        self.submit('uptime',server_status['uptime'])

        # operations
        for k, v in server_status['opcounters'].items():
            self.submit('total_operations', k, v)

        # memory
        for t in ['resident', 'virtual', 'mapped']:
            self.submit('memory', t, server_status['mem'][t])

        #network
        if 'network' in server_status:
            for t in ['bytesIn', 'bytesOut', 'numRequests']:
                self.submit('bytes', t, server_status['network'][t])

        # connections
        if 'current' in server_status['connections']:
            self.submit('connections', 'current', server_status['connections']['current'])
        if 'available' in server_status['connections']:
            self.submit('connections', 'available', server_status['connections']['available'])
        if 'totalCreated' in server_status['connections']:
            self.submit('connections', 'totalCreated', server_status['connections']['totalCreated'])

        #data flush
        if 'backgroundFlushing' in server_status:
            for t in ['flushes', 'average_ms', 'last_ms']:
                self.submit('data_flush', t, server_status['backgroundFlushing'][t])

        #asserts
        if 'asserts' in server_status:
            for t in ['regular', 'warning']:
                self.submit('asserts', t, server_status['asserts'][t])

        #page faults
        if 'extra_info' in server_status:
            self.submit('heap', 'page_faults', server_status['extra_info']['page_faults'])
            self.submit('heap', 'heap_usage_bytes',server_status['extra_info']['heap_usage_bytes'])


        #globalLocks
        if 'globalLock' in server_status:
            if 'totalTime' in server_status['globalLock']:
                self.submit('globalLock_totalTime', server_status['globalLock']['totalTime'])
            if 'currentQueue' in server_status['globalLock']:
                for t in ['total','readers','writers']:
                    self.submit('globalLock_currentQueue', t,server_status['globalLock']['currentQueue'][t])
            if 'activeClients' in server_status['globalLock']:
                for t in ['total','readers','writers']:
                    self.submit('globalLock_activeClients', t, server_status['globalLock']['activeClients'][t])

        #for version 2.x
	    if 'lockTime' in server_status['globalLock']:
                if self.lockTotalTime is not None and self.lockTime is not None:
                    if self.lockTime == server_status['globalLock']['lockTime']:
                        value = 0.0
                    else:
                        value = float(server_status['globalLock']['lockTime'] - self.lockTime) * 100.0 / float(server_status['globalLock']['totalTime'] - self.lockTotalTime)
                    self.submit('percent', 'lock_ratio', value)
                self.lockTime = server_status['globalLock']['lockTime']
            self.lockTotalTime = server_status['globalLock']['totalTime']


        #All locks only for version 3.x
        if eq_gt_3_0 and 'locks' in server_status:
            #deadlock counter
            if 'deadlockCount' in server_status['locks']['Global']:
                self.submit('deadlockCount','global', server_status['locks']['Global']['deadlockCount'])
            if 'deadlockCount' in server_status['locks']['Database']:
                self.submit('deadlockCount','database', server_status['locks']['Database']['deadlockCount'])
            #Average Wait time to acquire global lock
            if 'timeAcquiringMicros' and 'acquireWaitCount' in server_status['locks']['Global']:
                for t in ['r', 'w', 'R', 'W']:
                    total_wait_time = server_status['locks']['Global']['timeAcquiringMicros'][t]
                    total_wait_count = server_status['locks']['Global']['acquireWaitCount'][t]
                    self.submit('Lock_avgWaitTime','global', int(total_wait_time/total_wait_count))
            #Average Wait time to acquire global lock
            if 'timeAcquiringMicros' and 'acquireWaitCount' in server_status['locks']['Database']:
                for t in ['r', 'w', 'R', 'W']:
                    total_wait_time = server_status['locks']['Database']['timeAcquiringMicros'][t]
                    total_wait_count = server_status['locks']['Database']['acquireWaitCount'][t]
                    self.submit('avgWaitTime','database', int(total_wait_time/total_wait_count))

        #indexes for version 2.x
        if 'indexCounters' in server_status:
            accesses = None
            misses = None
            index_counters = server_status['indexCounters'] if at_least_2_4 else server_status['indexCounters']['btree']

            if self.accesses is not None:
                accesses = index_counters['accesses'] - self.accesses
                if accesses < 0:
                    accesses = None
            misses = (index_counters['misses'] or 0) - (self.misses or 0)
            if misses < 0:
                misses = None
            if accesses and misses is not None:
                self.submit('cache_ratio', 'cache_misses', int(misses * 100 / float(accesses)))
            else:
                self.submit('cache_ratio', 'cache_misses', 0)
            self.accesses = index_counters['accesses']
            self.misses = index_counters['misses']

        for mongo_db in self.mongo_db:
            db = con[mongo_db]
            if self.mongo_user and self.mongo_password:
                con[self.mongo_db[0]].authenticate(self.mongo_user, self.mongo_password)
            db_stats = db.command('dbstats')

            # stats counts
            self.submit('counter', 'object_count', db_stats['objects'], mongo_db)
            self.submit('counter', 'collections', db_stats['collections'], mongo_db)
            self.submit('counter', 'num_extents', db_stats['numExtents'], mongo_db)
            self.submit('counter', 'indexes', db_stats['indexes'], mongo_db)

            # stats sizes
            self.submit('file_size', 'storage', db_stats['storageSize'], mongo_db)
            self.submit('file_size', 'index', db_stats['indexSize'], mongo_db)
            self.submit('file_size', 'data', db_stats['dataSize'], mongo_db)

        con.close()


    def config(self, obj):
        for node in obj.children:
            if node.key == 'Port':
                self.mongo_port = int(node.values[0])
            elif node.key == 'Host':
                self.mongo_host = node.values[0]
            elif node.key == 'User':
                self.mongo_user = node.values[0]
            elif node.key == 'Password':
                self.mongo_password = node.values[0]
            elif node.key == 'Database':
                self.mongo_db = node.values
            elif node.key == 'Level':
                self.mongo_monitoring_level = node.values[0]
            else:
                collectd.warning("mongodb plugin: Unknown configuration key %s" % node.key)

mongodb = MongoDB()
collectd.register_read(mongodb.do_server_status)
collectd.register_config(mongodb.config)
