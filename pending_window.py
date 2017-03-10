from tuple import *

import os
import cPickle as pickle
from collections import deque

class PendingWindow(object):
    """docstring for PendingWindow"""
    def __init__(self, backup_dir, node):
        # TODO: not cut
        # each pending window (or node) only has a single downstream cut,
        # otherwise inconsistency occurs during truncating

        self.backup_dir = backup_dir
        os.mkdir(self.backup_dir)

        self.node = node

        # each backup file is named by the ending version, so the current writing one is named temporarily
        self.current_file = open(os.path.join(self.backup_dir, 'current'), 'wb')

        # the version that last truncation conducted against
        self.safe_version_file = open(os.path.join(self.backup_dir, 'safe_version'), 'w')
        self.safe_version_file.write(str(0))

        if self.node.type != 'sink':
            self.version_acks = dict()
            for n in self.node.downstream_connectors:
                self.version_acks[n] = deque()

    def append(self, tuple_):
        """Make an output tuple persistent, and complete a version if necessary
        """

        pickle.dump(tuple_, self.current_file)

        if isinstance(tuple_, BarrierTuple):
            self.current_file.close()
            os.rename(os.path.join(self.backup_dir, 'current'),
                os.path.join(self.backup_dir, str(tuple_.version)))

            self.current_file = open(os.path.join(self.backup_dir, 'current'), 'w')

    def extend(self, tuples):
        # TODO: can be improved
        for t in tuples:
            self.append(t)

    def truncate(self, version):
        """Delete files with filename <= version
        """

        self.safe_version_file.seek(0)
        self.safe_version_file.write(str(version))
        # note that this 'truncate()' means differently in Python from our definition
        self.safe_version_file.truncate()

        for f in os.listdir(self.backup_dir):
            if f.isdigit() and int(f) <= version:
                os.remove(os.path.join(self.backup_dir, f))

    def handle_version_ack(self, version_ack):
        self.version_acks[version_ack.sent_from].append(version_ack.version)

        if all(self.version_acks.values()) and set(map(lambda q: q[0], self.version_acks.values())) == 1:
            self.truncate(version_ack.version)

            for q in self.version_acks.values():
                q.popleft()

    def rewind(self, version):
        """Delete files with filename > version
        """

        for f in os.listdir(self.backup_dir):
            if f == 'current' or int(f) > version:
                os.remove(os.path.join(self.backup_dir, f))

        self.current_file = open(os.path.join(self.backup_dir, 'current'), 'w')

    def replay(self):
        """When both the node and pending window state are ready, replay the pending window before resuming
        """

        for v in sorted(os.listdir(self.backup_dir)):
            tuples = []
            with open(os.path.join(self.backup_dir, v), 'rb') as f:
                # TODO: incomplete writing
                while True:
                    try:
                        tuples.append(pickle.load(f))
                    except EOFError:
                        break

            self.node.multicast(self.node.downstream_nodes, tuples)
