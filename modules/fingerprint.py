from datetime import datetime, date, timedelta
import json
import os
import socket
import struct
import requests
from config import BASE_DIR
from models import (
    Employee, Attendance, FingerprintDevice, Setting, db
)


class FingerprintBase:
    """Base class for fingerprint device integration"""

    def __init__(self, device):
        self.device = device

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    def get_users(self):
        """Get all enrolled users"""
        raise NotImplementedError

    def get_attendance_logs(self):
        """Get attendance punch records"""
        raise NotImplementedError

    def enroll_user(self, user_id, name):
        raise NotImplementedError

    def delete_user(self, user_id):
        raise NotImplementedError


class ZKTecoDevice(FingerprintBase):
    """ZKTeco device integration using pyzk library"""

    def __init__(self, device):
        super().__init__(device)
        self.conn = None

    def connect(self):
        try:
            from pyzk import ZK
            self.zk = ZK(
                self.device.device_ip,
                port=4370,
                timeout=10,
                password=0,
                force_udp=False,
                ommit_ping=False
            )
            self.conn = self.zk.connect()
            return True
        except ImportError:
            return False
        except Exception as e:
            print(f"ZKTeco connect error: {e}")
            return False

    def disconnect(self):
        if self.conn:
            try:
                self.conn.disconnect()
            except:
                pass

    def get_users(self):
        if not self.conn:
            return []
        users = self.conn.get_users()
        return [{'user_id': u.user_id, 'name': u.name, 'privilege': u.privilege} for u in users]

    def get_attendance_logs(self):
        if not self.conn:
            return []
        logs = self.conn.get_attendance()
        return [
            {'user_id': l.user_id, 'timestamp': l.timestamp}
            for l in logs
        ]

    def enroll_user(self, user_id, name):
        if not self.conn:
            return False
        try:
            self.conn.save_user(
                user_id=str(user_id),
                name=name,
                password='',
                privilege=0
            )
            return True
        except Exception as e:
            print(f"Enroll error: {e}")
            return False

    def delete_user(self, user_id):
        if not self.conn:
            return False
        try:
            self.conn.delete_user(str(user_id))
            return True
        except Exception as e:
            print(f"Delete error: {e}")
            return False

    def clear_attendance(self):
        if self.conn:
            self.conn.clear_attendance()


class HTTPDevice(FingerprintBase):
    """HTTP API based fingerprint device (most Chinese devices)"""
    
    def _request(self, path, params=None, method='GET'):
        url = f"http://{self.device.device_ip}/{path}"
        try:
            if method == 'GET':
                resp = requests.get(url, params=params, timeout=5)
            else:
                resp = requests.post(url, json=params or {}, timeout=5)
            if resp.status_code == 200:
                return resp.json() if 'application/json' in resp.headers.get('Content-Type', '') else resp.text
        except Exception as e:
            print(f"HTTP device request error: {e}")
        return None

    def connect(self):
        try:
            resp = self._request('')
            return resp is not None
        except:
            return False

    def disconnect(self):
        pass

    def get_users(self):
        result = self._request('api/users')
        if isinstance(result, dict):
            return result.get('data', result)
        return []

    def get_attendance_logs(self, start=None, end=None):
        result = self._request('api/attendance', {
            'start': start or date.today().strftime('%Y-%m-%d'),
            'end': end or date.today().strftime('%Y-%m-%d')
        })
        if isinstance(result, dict):
            return result.get('data', result)
        return []

    def enroll_user(self, user_id, name):
        return self._request('api/enroll', {'user_id': user_id, 'name': name}, method='POST')


class TCPDevice(FingerprintBase):
    """Generic TCP protocol device (older devices)"""

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((self.device.device_ip, 4370))
            return True
        except Exception as e:
            print(f"TCP connect error: {e}")
            return False

    def disconnect(self):
        try:
            self.sock.close()
        except:
            pass

    def get_users(self):
        return []

    def get_attendance_logs(self):
        return []
    
    def enroll_user(self, user_id, name):
        return False


import os


class SimulatorDevice(FingerprintBase):
    """Simulator for testing without physical device"""
    
    def connect(self):
        return True

    def disconnect(self):
        pass

    def get_users(self):
        emps = Employee.query.filter(Employee.fingerprint_id.isnot(None)).all()
        return [{'user_id': e.fingerprint_id, 'name': e.full_name} for e in emps]

    def get_attendance_logs(self, test_mode=False):
        log_dir = os.path.join(BASE_DIR, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'fingerprint_punches.txt')
        events = []
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split('|')
                    if len(parts) >= 2:
                        events.append({
                            'fingerprint_id': parts[0],
                            'timestamp': parts[1]
                        })
        return events


class FingerprintManager:
    """Main manager for fingerprint devices"""

    @staticmethod
    def get_device_adapter(device):
        adapters = {
            'zkteco': ZKTecoDevice,
            'http': HTTPDevice,
            'tcp': TCPDevice,
            'simulator': SimulatorDevice,
        }
        adapter_class = adapters.get(device.device_type, HTTPDevice)
        return adapter_class(device)

    @staticmethod
    def sync_attendance(device=None):
        """Pull attendance logs from device and record them"""
        
        # For simulators - flush the test log
        if device and device.device_type == 'simulator':
            os.makedirs(os.path.join(BASE_DIR, 'logs'), exist_ok=True)
            log_file = os.path.join(BASE_DIR, 'logs', 'fingerprint_punches.txt')
            if os.path.exists(log_file):
                os.remove(log_file)

        devices = [device] if device else FingerprintDevice.query.filter_by(status='active').all()
        synced = 0
        skipped = 0
        errors = []

        for dev in devices:
            adapter = FingerprintManager.get_device_adapter(dev)
            if not adapter.connect():
                errors.append(f"{dev.name}: فشل الاتصال")
                continue

            try:
                logs = adapter.get_attendance_logs()
                for log in logs:
                    # Find employee by fingerprint ID
                    fp_id = log.get('user_id') or log.get('fingerprint_id')
                    if not fp_id:
                        continue
                    
                    emp = Employee.query.filter_by(fingerprint_id=str(fp_id)).first()
                    if not emp:
                        skipped += 1
                        continue

                    # Parse timestamp
                    ts = log.get('timestamp')
                    if isinstance(ts, str):
                        try:
                            dt = datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S')
                        except:
                            try:
                                dt = datetime.strptime(ts[:19], '%Y-%m-%dT%H:%M:%S')
                            except:
                                continue
                    elif isinstance(ts, datetime):
                        dt = ts
                    else:
                        continue

                    # Record attendance
                    punch_type = FingerprintManager._determine_punch_type(emp, dt)
                    result = FingerprintManager._record_punch(emp, dt, dev.id, punch_type)
                    
                    if result in ('check_in', 'check_out', 'updated'):
                        synced += 1
                    else:
                        skipped += 1

            except Exception as e:
                errors.append(f"{dev.name}: {str(e)}")
            finally:
                adapter.disconnect()

        return {'synced': synced, 'skipped': skipped, 'errors': errors}

    @staticmethod
    def _shift_times(emp):
        """إرجاع مواعيد (work_start, work_end, tolerance, grace_out) حسب وردية الموظف أو الموحدة."""
        shift = None
        if getattr(emp, 'shift_id', None):
            from models import Shift as _Shift
            shift = _Shift.query.get(emp.shift_id)
        work_start = Setting.get('work_start', '08:00')
        work_end = Setting.get('work_end', '17:00')
        tolerance = int(Setting.get('late_tolerance', '15'))
        grace_out = 30
        if shift:
            work_start = shift.start_time.strftime('%H:%M')
            work_end = shift.end_time.strftime('%H:%M')
            tolerance = shift.late_tolerance
            grace_out = shift.grace_minutes_out
        return work_start, work_end, tolerance, grace_out

    @staticmethod
    def _determine_punch_type(emp, dt):
        work_start, _e, _t, _g = FingerprintManager._shift_times(emp)
        try:
            start_h, start_m = map(int, work_start.split(':'))
        except:
            start_h, start_m = 8, 0
        start_minutes = start_h * 60 + start_m
        punch_minutes = dt.hour * 60 + dt.minute
        # First half of workday = check-in, second half = check-out
        return 'check_in' if punch_minutes <= start_minutes + 120 else 'check_out'

    @staticmethod
    def _record_punch(emp, dt, device_id, punch_type):
        """Record a punch to attendance database"""
        existing = Attendance.query.filter_by(
            employee_id=emp.id, date=dt.date()
        ).first()

        work_start, work_end, tolerance, grace_out = FingerprintManager._shift_times(emp)

        if punch_type == 'check_in':
            if existing:
                # Update check-in if first or earlier
                if not existing.check_in_time or dt.time() < existing.check_in_time:
                    existing.check_in_time = dt.time()
                    existing.device_id = device_id
                    if emp.shift_id:
                        existing.shift_id = emp.shift_id
                    db.session.commit()
                    return 'updated'
                return 'skipped'
            else:
                attendance = Attendance(
                    employee_id=emp.id,
                    date=dt.date(),
                    check_in_time=dt.time(),
                    device_id=device_id,
                    status='present',
                    shift_id=emp.shift_id,
                )
                # Check if late
                try:
                    start_h, start_m = map(int, work_start.split(':'))
                    work_start_dt = datetime(dt.year, dt.month, dt.day, start_h, start_m)
                    late_minutes = (dt - work_start_dt).total_seconds() / 60
                    if late_minutes > tolerance:
                        attendance.status = 'late'
                        attendance.late_minutes = int(round(late_minutes))
                except:
                    pass

                db.session.add(attendance)
                db.session.commit()
                return 'check_in'

        elif punch_type == 'check_out':
            if existing:
                if not existing.check_out_time:
                    existing.check_out_time = dt.time()
                    existing.device_id = device_id
                    if emp.shift_id:
                        existing.shift_id = emp.shift_id
                    
                    # Calculate overtime
                    try:
                        end_h, end_m = map(int, work_end.split(':'))
                        work_end_dt = datetime(dt.year, dt.month, dt.day, end_h, end_m)
                        ot_minutes = (dt - work_end_dt).total_seconds() / 60
                        # Add grace for lunch/breaks
                        if ot_minutes > grace_out:
                            existing.overtime_hours = round((ot_minutes - grace_out) / 60, 2)
                        # Early leave
                        if ot_minutes < 0 and dt.time() < datetime(dt.year, dt.month, dt.day, end_h, end_m).time():
                            existing.early_leave_minutes = int(round(abs(ot_minutes)))
                    except:
                        pass

                    db.session.commit()
                    return 'check_out'
                return 'skipped'
        return 'skipped'

    @staticmethod
    def manual_punch(emp, dt=None, punch_type=None):
        """Manual attendance entry"""
        dt = dt or datetime.now()
        return FingerprintManager._record_punch(emp, dt, None, punch_type or 'check_in')

    @staticmethod
    def test_simulator_punch(fingerprint_id, opts=None):
        """Create a test punch event (for simulator / development)"""
        opts = opts or {}
        os.makedirs(os.path.join(BASE_DIR, 'logs'), exist_ok=True)
        log_file = os.path.join(BASE_DIR, 'logs', 'fingerprint_punches.txt')
        
        # Generate timestamp
        t = opts.get('timestamp') or datetime.now()
        offset_hours = opts.get('offset_hours', 0)
        if offset_hours:
            t = datetime.now() + timedelta(hours=offset_hours)

        mode = opts.get('mode', 'auto')
        if mode == 'check_in_only':
            t = datetime(t.year, t.month, t.day, 8, 0, 0)
        elif mode == 'check_out_only':
            t = datetime(t.year, t.month, t.day, 17, 30, 0)
        elif mode == 'late':
            t = datetime(t.year, t.month, t.day, 9, 30, 0)
        elif mode == 'test_day':
            t = datetime(t.year, t.month, t.day, 8, 5, 0)

        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{fingerprint_id}|{t.strftime('%Y-%m-%d %H:%M:%S')}\n")
        return {'success': True, 'message': f"تم تسجيل بصمة {fingerprint_id} في {t.strftime('%H:%M:%S')}"}