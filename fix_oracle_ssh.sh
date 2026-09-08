#!/bin/bash
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

# 1. Enable PermitUserEnvironment
sudo sed -i 's/^#PermitUserEnvironment no/PermitUserEnvironment yes/' /etc/ssh/sshd_config
# If the line doesn't exist, add it
grep -q '^PermitUserEnvironment' /etc/ssh/sshd_config || echo 'PermitUserEnvironment yes' | sudo tee -a /etc/ssh/sshd_config

# 2. Also accept PATH from client
grep -q '^AcceptEnv.*PATH' /etc/ssh/sshd_config || sudo sed -i 's/^AcceptEnv LANG LC_\*/AcceptEnv LANG LC_* PATH/' /etc/ssh/sshd_config

# 3. Create ~/.ssh/environment
echo 'PATH=/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin' > ~/.ssh/environment
chmod 600 ~/.ssh/environment

# 4. Restart sshd
sudo systemctl restart sshd 2>&1 || sudo service ssh restart 2>&1

echo "=== VERIFY ==="
grep PermitUserEnvironment /etc/ssh/sshd_config
grep AcceptEnv /etc/ssh/sshd_config
cat ~/.ssh/environment
echo "DONE"
