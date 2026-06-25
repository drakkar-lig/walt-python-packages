% rebase('base.tpl', title='WALT - Quick links to webapps')

<p>WalT allows you to <a href="/doc/device-expose.html">expose a service</a>
running on a node (or another device, such as a switch) by mirroring
the TCP port to a port of the WalT server.</p>

% if len(links_info) == 0:

However, no port is currently exposed.
Refresh this page once you have exposed a port.

% else:

The following devices have some of their ports exposed:
% for dev_type, dev_name, dev_links in links_info:
<p>
<details>
  <summary>{{dev_type}} <b>{{dev_name}}</b></summary>
  <ul>
    % for dev_port, label in dev_links:
    <li>port
      <a href="/links/{{dev_name}}/tcp/{{dev_port}}">{{dev_port}}</a>
      % if label is not None:
          ({{label}})
      % end
    </li>
    % end
  </ul>
</details>
</p>
% end

% end

<p>See <a href="/doc/device-expose.html">this</a> documentation topic
for more info.</p>
