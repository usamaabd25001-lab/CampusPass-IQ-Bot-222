from __future__ import annotations

ONES = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة"]
TENS = ["", "عشرة", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
TEENS = {11:"أحد عشر",12:"اثنا عشر",13:"ثلاثة عشر",14:"أربعة عشر",15:"خمسة عشر",16:"ستة عشر",17:"سبعة عشر",18:"ثمانية عشر",19:"تسعة عشر"}
HUNDREDS = ["", "مائة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة", "سبعمائة", "ثمانمائة", "تسعمائة"]

def _under_1000(n:int)->str:
    parts=[]
    if n>=100: parts.append(HUNDREDS[n//100]); n%=100
    if n:
        if parts: parts.append("و")
        if n in TEENS: parts.append(TEENS[n])
        else:
            u,t=n%10,n//10
            if u and t: parts.append(f"{ONES[u]} و{TENS[t]}")
            elif t: parts.append(TENS[t])
            else: parts.append(ONES[u])
    return " ".join(parts)

def iqd_in_words(amount:int)->str:
    """Readable Iraqi dinar amounts for settlement/payment messages (0..999,999,999)."""
    amount=int(amount)
    if amount<0 or amount>=1_000_000_000: raise ValueError("المبلغ خارج النطاق")
    if amount==0: return "صفر دينار"
    parts=[]
    millions, rem=divmod(amount,1_000_000)
    thousands, units=divmod(rem,1000)
    if millions:
        if millions==1: parts.append("مليون")
        elif millions==2: parts.append("مليونان")
        else: parts.append(f"{_under_1000(millions)} ملايين")
    if thousands:
        if parts: parts.append("و")
        if thousands==1: parts.append("ألف")
        elif thousands==2: parts.append("ألفان")
        elif 3<=thousands<=10: parts.append(f"{_under_1000(thousands)} آلاف")
        else: parts.append(f"{_under_1000(thousands)} ألف")
    if units:
        if parts: parts.append("و")
        parts.append(_under_1000(units))
    return " ".join(parts)+" دينار"
