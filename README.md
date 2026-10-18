# Light Overlay

نافذة صغيرة خفيفة تبقى فوق الشاشة وتعرض:

- نسبة استخدام المعالج
- حرارة المعالج
- الرام
- نسبة استخدام كرت NVIDIA
- حرارة كرت NVIDIA

اسحب النافذة بزر الفأرة الأيسر. الضغط بالزر الأيمن يظهر قائمة لإخفاء أي قراءة أو إغلاق التطبيق.

## التشغيل

شغّل الملف:

`LightOverlay.exe`

ما يحتاج تثبيت بايثون.

## حرارة المعالج

ويندوز لا يعطي حرارة معالج AMD مباشرة. حرارة الكرت تظهر وحدها لأن تعريف NVIDIA يبقى شغّالًا. حرارة المعالج تحتاج برنامج LibreHardwareMonitor.

1. افتح صفحة الإصدارات:

https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/latest

2. حمّل الملف الذي اسمه:

`LibreHardwareMonitor.zip`

3. لا تحمّل الملف الذي يظهر في اسمه `NET.10`. تلك النسخة تطلب .NET 10، وويندوز غالبًا يعطيك رسالة أن .NET ناقص حتى بعد تثبيت نسخة أخرى.

4. فك الضغط. النسخة العادية تعمل على .NET Framework 4.8 الموجود في ويندوز 10 وويندوز 11.

5. أول تشغيل: اضغط بزر الفأرة الأيمن على `LibreHardwareMonitor.exe` واختر تشغيل كمسؤول.

6. من القائمة:

`Options` ثم `Remote Web Server` ثم فعّل `Run`

المنفذ يبقى `8085`.

7. اترك البرنامج يعمل في الخلفية. تقدر تصغّر نافذته. إذا أغلقته بالكامل، حرارة المعالج في Light Overlay ترجع `N/A`.

إذا وضعت `LibreHardwareMonitor.exe` بجانب `LightOverlay.exe`، أو داخل مجلد اسمه `LibreHardwareMonitor` بجانب التطبيق، يحاول Light Overlay تشغيله عندما تكون الحرارة غير متاحة.

## البناء من المصدر

```powershell
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name LightOverlay overlay.py
```

الملف الناتج يكون هنا:

`dist\LightOverlay.exe`
