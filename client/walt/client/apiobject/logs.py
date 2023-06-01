from walt.client.apiobject.base import APIObjectBase, api_namedtuple_cls
from walt.client.apitools import get_devices_names, silent_server_link
from walt.client.log import WalTLogShowOrWait


class APILogsSubModule(APIObjectBase):
    """API submodule for WALT logs"""

    def get_logs(self, realtime=False, history=None, issuers="my-nodes", timeout=-1):
        """Iterate over historical or realtime logs"""
        if realtime is False and history is None:
            raise Exception(
                'At least one of the options "realtime" and "history"'
                ' must be specified.'
            )
        with silent_server_link() as server:
            if history is not None:
                range_analysis = WalTLogShowOrWait.analyse_history_range(
                    server, history
                )
                if not range_analysis[0]:
                    raise Exception(
                        """Invalid "history" value. See 'walt help show log-history'."""
                    )
                history_range = range_analysis[1]
            else:
                history_range = None
            issuers = get_devices_names(
                server, issuers, allowed_device_set="server,all-nodes"
            )
            if issuers is None:
                raise Exception("""Invalid set of issuers.""")
        return self._iterate(history_range, realtime, issuers, timeout)

    def _iterate(self, history_range, realtime, issuers, timeout):
        from walt.client.apiobject.nodes import APINodeFactory
        from walt.client.apiobject.server import APIServerFactory

        nt_cls = None
        it = WalTLogShowOrWait.start_streaming(
            history_range, realtime, issuers, None, None, None, timeout
        )
        for record in it:
            if record["issuer"] == "walt-server":
                record["issuer"] = APIServerFactory.create()
            else:  # issuer is a node
                record["issuer"] = APINodeFactory.create(record["issuer"])
            if nt_cls is None:
                nt_cls = api_namedtuple_cls("Log", list(record.keys()))
            yield nt_cls(**record)


def get_api_logs_submodule():
    return APILogsSubModule()
