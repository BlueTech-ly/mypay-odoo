# MyPay Payment Provider for Odoo 18

Accept Libyan payments in Odoo through [MyPay](https://mypay.ly) hosted checkout. Payments are confirmed via **Payment Status enquiry** (Odoo calls MyPay). Signed **webhooks** are optional when a public HTTPS URL is available.

## English

### Requirements

- Odoo 18 Community (or Enterprise)
- A MyPay merchant account with API credentials (Client ID + Secret ID)
- Public HTTPS URL only if you want **inbound webhooks** (optional)

### Installation

1. Copy the `payment_mypay` folder into an Odoo addons path, or clone this repository and add the repo root to `addons_path`.
2. Update the Apps list and install **MyPay**.
3. Open **Invoicing / Accounting → Configuration → Payment Providers → MyPay**.
4. Set the provider state to **Test** (sandbox) or **Enabled** (production).
5. Enter **Client ID** and **Secret ID** from the MyPay merchant dashboard.
6. (Optional) Paste **Webhook Secret** and copy the **Webhook URL** into MyPay when you have public HTTPS.
7. Publish the provider and assign a payment journal if prompted.

| Provider state | API base URL |
|---|---|
| Test | `https://mypay.ly/pay/sandbox/api/v1` |
| Enabled | `https://mypay.ly/pay/api/v1` |

**Enabled** does **not** require public HTTPS. A warning appears when webhooks cannot reach Odoo; Payment Status + return URL + cron still confirm payments.

### Payment flow

1. The customer selects MyPay at checkout (or a specific MyPay gateway method such as `sahary-pay` / `edfali`).
2. Odoo requests a one-time access token, then creates a payment (`custom` = transaction reference). When a gateway method is selected, Odoo sends `payment_gateway` with that MyPay alias.
3. The shopper is redirected to MyPay hosted checkout. With the generic **MyPay** method, they choose a gateway on MyPay. With a gateway alias plus a Libyan phone (`09xxxxxxxx`), Auto-Submit can skip the all-gateways page.
4. On browser return, Odoo calls `GET /payment/status` (Basic Auth) and marks the transaction **Done** when status is `success`.
5. A cron job re-checks draft/pending MyPay transactions every 5 minutes (covers closed browsers), and re-checks recently canceled ones for a late `success` (Cancel→Success race).
6. If configured, a signed webhook (`X-MyPay-Signature`) can also confirm payment.

#### Staff pay on behalf of a customer

On a posted customer invoice with a residual amount, use **Pay via MyPay**:

1. Choose a payment gateway (MyPay alias: `moamalat`, `masrafi-pay`, `yasr-pay`, `sahary-pay`, `edfali`, `sadad`, `mobicash`, …).
2. Enter a Libyan mobile number (`09xxxxxxxx`) so MyPay can Auto-Submit and skip the all-gateways page.
3. **Open MyPay** — the employee or customer completes OTP / bank approval on the hosted page.

Refunds are not available through the MyPay API; handle them manually in Odoo and in the MyPay dashboard.

### Verify the scheduled action (Cron)

Payment Status confirmation for closed browsers depends on Odoo’s cron:

1. Enable developer mode.
2. Open **Settings → Technical → Automation → Scheduled Actions**.
3. Find **MyPay: sync pending payment status** and confirm it is **Active** (every 5 minutes).
4. Ensure the Odoo server runs cron (default single-process mode, or workers with cron enabled).

Without this job, return/cancel URLs still confirm when the shopper comes back; only the “closed browser” path needs cron.

### Sandbox E2E checklist (manual)

With MyPay in **Test** and sandbox credentials:

1. **Happy path:** pay an invoice/order → return to Odoo → transaction **Done**.
2. **Staff on behalf:** invoice → **Pay via MyPay** → pick gateway alias + Libyan phone `09…` → Open MyPay (should not show the full gateway grid, or the chosen gateway is pre-selected) → **Done**.
3. **Closed browser:** complete payment on MyPay, close the tab before return → wait for cron → **Done**.
4. **Cancel then pay:** open cancel while MyPay still `pending`, then complete payment → stay open or revive via cron → **Done**.
5. **Optional webhook:** with public HTTPS, paste Webhook URL + secret → pay → webhook marks **Done** even if return is skipped.

### Payment Status vs webhooks

| Path | Direction | Needs public HTTPS on Odoo? |
|---|---|---|
| Payment Status | Odoo → MyPay | No |
| Return / cancel URL | Shopper browser → Odoo | Reachable by the shopper |
| Webhook | MyPay → Odoo | Yes (optional) |

### Optional public HTTPS for webhooks

Use a tunnel or reverse proxy if you want faster inbound confirmation.

#### Local development (Cloudflare Tunnel)

```bash
docker compose up
./scripts/dev-webhook-tunnel.sh
```

Set `web.base.url` to the printed `https://….trycloudflare.com` URL, then paste the Webhook URL into MyPay.

Named tunnel: set `TUNNEL_TOKEN` in `.env`, then `docker compose --profile tunnel up`.

#### Production (Caddy + Let's Encrypt)

```bash
cp .env.example .env   # DOMAIN + ACME_EMAIL
docker compose -f docker-compose.prod.yml up -d
```

Set `web.base.url = https://YOUR_DOMAIN` and enable proxy mode.

### Local testing with Docker

```bash
docker compose up
```

Open `http://localhost:8069`, install **MyPay**, and use Status enquiry (no tunnel required for basic confirmation).

### Point of Sale

MyPay in POS uses Odoo’s online payment QR flow (`pos_online_payment`). After installing **Point of Sale**, the **POS MyPay** module installs automatically.

1. Publish MyPay (**Test** or **Enabled**) under Payment Providers.
2. **Point of Sale → Configuration → Payment Methods** and open **MyPay** (type Online). Confirm **Allowed Providers** includes MyPay.
3. **Point of Sale → Configuration → Point of Sale** → your shop → **Payment Methods** → add **MyPay**.
4. Close any open session, then open a new one.
5. On the payment screen choose **MyPay**. A QR code / link appears; the customer pays on the MyPay hosted page. The POS order is validated when the payment succeeds.

POS uses the company currency. MyPay only accepts **LYD**, so the company (or a dedicated POS company) must use LYD.

### Release packages

Build clean upload zips (no `__pycache__` / `.DS_Store`):

```bash
./scripts/build-release.sh
```

Artifacts in `dist/`:

| File | Use |
|---|---|
| `payment_mypay-VERSION.zip` | Odoo Apps / install main module |
| `pos_mypay-VERSION.zip` | Odoo Apps / POS companion |
| `mypay-odoo-VERSION.zip` | Private deploy (both modules + README + LICENSE) |

### Support

MyPay — https://mypay.ly

---

## العربية

إضافة أودو 18 لقبول المدفوعات عبر صفحة MyPay المستضافة. يُؤكَّد الدفع عبر **استعلام Payment Status** (أودو يستدعي MyPay). **الويب هوك** اختياري عند توفر HTTPS عام.

### المتطلبات

- أودو 18 Community (أو Enterprise)
- حساب تاجر MyPay مع معرف العميل والمفتاح السري
- عنوان HTTPS عام فقط إذا رغبت بالويب هوك الوارد (اختياري)

### التثبيت

1. انسخ مجلد `payment_mypay` إلى مسار الإضافات، أو أضف جذر هذا المستودع إلى `addons_path`.
2. حدّث قائمة التطبيقات وثبّت **MyPay**.
3. افتح **الفوترة / المحاسبة ← الإعدادات ← مزودو الدفع ← MyPay**.
4. اضبط الحالة على **اختبار** أو **مفعّل**.
5. أدخل **معرف العميل** و**المفتاح السري**.
6. (اختياري) سر الويب هوك ورابطه عند توفر HTTPS عام.
7. انشر المزود واربط دفتر يومية الدفع عند الطلب.

| حالة المزود | عنوان الـ API |
|---|---|
| اختبار | `https://mypay.ly/pay/sandbox/api/v1` |
| مفعّل | `https://mypay.ly/pay/api/v1` |

حالة **مفعّل** لا تشترط HTTPS عام. يظهر تحذير إن تعذّر وصول الويب هوك؛ التأكيد يبقى عبر Status ورابط العودة والـ Cron.

### تدفق الدفع

1. يختار العميل MyPay عند الدفع (أو طريقة بوابة محددة مثل `sahary-pay` / `edfali`).
2. يطلب أودو رمز وصول ثم ينشئ الدفع (`custom` = مرجع المعاملة). عند اختيار بوابة يُرسل `payment_gateway` بـ alias الخاص بها.
3. يُوجَّه المتسوق لصفحة MyPay. مع خيار **MyPay** العام يختار البوابة هناك. مع alias + هاتف ليبي (`09xxxxxxxx`) يمكن تفعيل Auto-Submit وتجاوز صفحة كل البوابات.
4. عند العودة يستعلم أودو `GET /payment/status` ويؤكّد عند `success`.
5. مهمة مجدولة كل 5 دقائق تعيد فحص المعاملات المعلّقة، وتعيد فحص الملغاة حديثاً إن نجح الدفع لاحقاً.
6. إن ضُبط الويب هوك يمكنه أيضاً تأكيد الدفع.

#### دفع الموظف نيابة عن العميل

على فاتورة عميل مرحّلة ذات رصيد متبقٍ استخدم **الدفع عبر MyPay**:

1. اختر بوابة الدفع (alias: `moamalat`، `masrafi-pay`، `yasr-pay`، `sahary-pay`، `edfali`، `sadad`، `mobicash`، …).
2. أدخل جوالاً ليبياً (`09xxxxxxxx`) لتفعيل Auto-Submit وتجاوز صفحة كل البوابات.
3. **فتح MyPay** — يكمل الموظف أو العميل OTP / موافقة البنك على الصفحة المستضافة.

الاسترداد عبر API غير مدعوم؛ عالجه يدوياً في أودو ولوحة MyPay.

### التحقق من المهمة المجدولة (Cron)

1. فعّل وضع المطوّر.
2. **الإعدادات ← تقني ← أتمتة ← الإجراءات المجدولة**.
3. تأكد أن **MyPay: sync pending payment status** **نشط** (كل 5 دقائق).
4. تأكد أن خادم أودو يشغّل الـ Cron.

بدونها يعمل التأكيد عند العودة/الإلغاء؛ مسار «إغلاق المتصفح» يعتمد على الـ Cron.

### قائمة E2E لـ Sandbox (يدوية)

1. دفع ناجح مع العودة → Done.  
2. دفع الموظف نيابة: فاتورة → **الدفع عبر MyPay** → اختيار alias + هاتف `09…` → فتح MyPay (بدون شبكة كل البوابات أو مع بوابة مسبقة الاختيار) → Done.  
3. دفع ناجح ثم إغلاق المتصفح → انتظار Cron → Done.  
4. Cancel والدفع ما زال pending ثم إكمال الدفع → Done عبر Cron/الإحياء.  
5. (اختياري) Webhook مع HTTPS.

### Payment Status مقابل الويب هوك

| المسار | الاتجاه | هل يلزم HTTPS عام على أودو؟ |
|---|---|---|
| Payment Status | أودو → MyPay | لا |
| رابط العودة / الإلغاء | متصفح العميل → أودو | أن يصل إليه العميل |
| الويب هوك | MyPay → أودو | نعم (اختياري) |

### HTTPS اختياري للويب هوك

للتطوير: `docker compose up` ثم `./scripts/dev-webhook-tunnel.sh`.  
للإنتاج: `docker compose -f docker-compose.prod.yml up -d` مع `DOMAIN` و`ACME_EMAIL`.

### نقطة البيع (POS)

بعد تثبيت **نقطة البيع** تُثبَّت وحدة **POS MyPay** تلقائياً. أضف طريقة MyPay للمتجر وافتح جلسة جديدة. العملة يجب أن تكون **LYD**.

### حزم الإصدار

```bash
./scripts/build-release.sh
```

الملفات في `dist/`: `payment_mypay-VERSION.zip` و`pos_mypay-VERSION.zip` للرفع على Odoo Apps، و`mypay-odoo-VERSION.zip` للنشر الخاص.

### الدعم

MyPay — https://mypay.ly
