# -*- coding: utf-8 -*-
"""
옥탑밭 회원관리 — 단일 파일 Flask 앱
요구사항 반영:
- 만료일 직접 지정 필드 (미지정 시 멤버십별 자동 계산)
- 만료일 지난 경우 <만료> 태그 표시 + D-Day 색상
- 테이블 컬럼 필터(검색, 멤버십, 만료상태, 가입일/만료일 기간)
- 회원 삭제 기능 추가 (POST)

실행 방법 (macOS)
1) python3 -m venv .venv && source .venv/bin/activate
2) pip install Flask==3.0.3 Flask-SQLAlchemy==3.1.1 SQLAlchemy==2.0.32
3) python3 app.py  → http://127.0.0.1:5001
"""

from datetime import date, datetime, timedelta
import io, csv
from typing import Optional

from flask import Flask, request, redirect, url_for, render_template_string, send_file, flash
from flask_sqlalchemy import SQLAlchemy
from jinja2 import DictLoader

# -----------------
# 앱/DB 설정
# -----------------
app = Flask(__name__)
app.config["SECRET_KEY"] = "otobap-dev-secret"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///members.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# -----------------
# 모델
# -----------------
class Member(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    contact = db.Column(db.String(50))  # 연락처
    membership_type = db.Column(db.String(20), nullable=False)  # 월간/분기/연간/상자텃밭만
    join_date = db.Column(db.Date, nullable=False)
    expiry_date = db.Column(db.Date, nullable=True)
    source = db.Column(db.String(120))  # 가입경로
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

with app.app_context():
    db.create_all()

# -----------------
# 유틸
# -----------------
DAYS_MAP = {"월간": 30, "분기": 90, "연간": 365, "상자텃밭만": 14}

def parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def auto_expiry(join_date: Optional[date], membership_type: str) -> Optional[date]:
    if not join_date:
        return None
    days = DAYS_MAP.get(membership_type)
    return join_date + timedelta(days=days) if days else None

# -----------------
# 템플릿 (단일파일)
# -----------------
BASE_HTML = r"""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>옥탑밭회원관리</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='0.9em' font-size='90'%3E%F0%9F%91%A8%F0%9F%8C%BE%3C/text%3E%3C/svg%3E" />
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 text-gray-800">
  <div class="max-w-7xl mx-auto p-6">
    <header class="flex items-center justify-between mb-5">
      <h1 class="text-2xl font-bold flex items-center gap-2">👨‍🌾 옥탑밭회원관리</h1>
      <nav class="flex gap-2">
        <a href="{{ url_for('index') }}" class="px-3 py-2 rounded bg-blue-500 hover:bg-blue-600 text-white shadow">목록</a>
        <a href="{{ url_for('export_csv', **request.args) }}" class="px-3 py-2 rounded bg-slate-600 hover:bg-slate-700 text-white shadow">CSV</a>
      </nav>
    </header>

    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div class="space-y-2 mb-4">
          {% for m in messages %}
          <div class="px-4 py-2 bg-amber-100 text-amber-800 rounded">{{ m }}</div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}

    {% block content %}{% endblock %}
  </div>
</body>
</html>
"""

INDEX_HTML = r"""
{% extends 'base.html' %}
{% block content %}
  <!-- 등록/수정 폼 -->
  <div class="bg-white rounded-lg shadow p-4 mb-6">
    <form method="post" class="grid md:grid-cols-3 gap-3">
      <input name="name" required placeholder="이름*" class="border rounded px-3 py-2" />
      <input name="contact" placeholder="연락처" class="border rounded px-3 py-2" />

      <select name="membership_type" class="border rounded px-3 py-2">
        {% for t in ['월간','분기','연간','상자텃밭만'] %}
        <option value="{{t}}">{{t}}</option>
        {% endfor %}
      </select>

      <input type="date" name="join_date" required class="border rounded px-3 py-2" />

      <!-- 만료일 직접 지정 (선택) → 비워두면 자동 계산 -->
      <input type="date" name="expiry_date" placeholder="만료일(선택)" class="border rounded px-3 py-2" />

      <input name="source" placeholder="가입경로" class="border rounded px-3 py-2" />
      <input name="note" placeholder="메모" class="border rounded px-3 py-2 md:col-span-2" />

      <button class="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded">등록</button>
    </form>
    <p class="text-xs text-gray-500 mt-2">만료일을 비우면 멤버십 종류에 따라 자동 지정됩니다. (월간 30일 / 분기 90일 / 연간 365일 / 상자텃밭만 14일)</p>
  </div>

  <!-- 컬럼 필터 폼 -->
  <form method="get" class="bg-white rounded-lg shadow p-4 mb-4 grid md:grid-cols-6 gap-3">
    <input type="text" name="q" value="{{ request.args.get('q','') }}" placeholder="이름/연락처/경로/메모 검색" class="border rounded px-3 py-2 md:col-span-2" />

    <select name="membership_type" class="border rounded px-3 py-2">
      <option value="">멤버십 전체</option>
      {% for t in ['월간','분기','연간','상자텃밭만'] %}
      <option value="{{t}}" {% if request.args.get('membership_type')==t %}selected{% endif %}>{{t}}</option>
      {% endfor %}
    </select>

    <select name="expired" class="border rounded px-3 py-2">
      <option value="">만료상태 전체</option>
      <option value="active" {% if request.args.get('expired')=='active' %}selected{% endif %}>유효</option>
      <option value="expired" {% if request.args.get('expired')=='expired' %}selected{% endif %}>만료</option>
    </select>

    <input type="date" name="join_from" value="{{ request.args.get('join_from','') }}" class="border rounded px-3 py-2" />
    <input type="date" name="join_to" value="{{ request.args.get('join_to','') }}" class="border rounded px-3 py-2" />

    <div class="md:col-span-6 flex gap-2">
      <input type="date" name="exp_from" value="{{ request.args.get('exp_from','') }}" class="border rounded px-3 py-2" />
      <input type="date" name="exp_to" value="{{ request.args.get('exp_to','') }}" class="border rounded px-3 py-2" />
      <button class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded">필터 적용</button>
      <a class="px-4 py-2 bg-slate-200 hover:bg-slate-300 rounded" href="{{ url_for('index') }}">초기화</a>
    </div>
  </form>

  <!-- 목록 -->
  <div class="bg-white rounded-lg shadow overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="bg-gray-100 text-gray-700">
        <tr>
          <th class="p-2 text-left">ID</th>
          <th class="p-2 text-left">이름</th>
          <th class="p-2 text-left">연락처</th>
          <th class="p-2 text-left">멤버십</th>
          <th class="p-2 text-left">가입일</th>
          <th class="p-2 text-left">만료일</th>
          <th class="p-2 text-left">상태</th>
          <th class="p-2 text-left">D-Day</th>
          <th class="p-2 text-left">가입경로</th>
          <th class="p-2 text-left">메모</th>
          <th class="p-2 text-right">관리</th>
        </tr>
      </thead>
      <tbody>
        {% for m in members %}
        {% set days_left = (m.expiry_date - today).days if m.expiry_date else None %}
        {% set state = '만료' if (m.expiry_date and m.expiry_date < today) else '유효' %}
        <tr class="border-t hover:bg-gray-50">
          <td class="p-2">{{ m.id }}</td>
          <td class="p-2">{{ m.name }}</td>
          <td class="p-2">{{ m.contact or '' }}</td>
          <td class="p-2">{{ m.membership_type }}</td>
          <td class="p-2">{{ m.join_date.strftime('%Y-%m-%d') }}</td>
          <td class="p-2">{{ m.expiry_date.strftime('%Y-%m-%d') if m.expiry_date else '' }}</td>
          <td class="p-2">
            {% if state == '만료' %}
              <span class="inline-block px-2 py-0.5 rounded bg-red-100 text-red-700 text-xs">&lt;만료&gt;</span>
            {% else %}
              <span class="inline-block px-2 py-0.5 rounded bg-emerald-100 text-emerald-700 text-xs">유효</span>
            {% endif %}
          </td>
          <td class="p-2">
            {% if days_left is not none %}
              {% if days_left < 0 %}
                <span class="text-red-600 font-semibold">D{{ days_left }}</span>
              {% elif days_left <= 7 %}
                <span class="text-red-600 font-semibold">D-{{ days_left }}</span>
              {% elif days_left <= 30 %}
                <span class="text-orange-500 font-semibold">D-{{ days_left }}</span>
              {% else %}
                <span class="text-emerald-600 font-semibold">D-{{ days_left }}</span>
              {% endif %}
            {% endif %}
          </td>
          <td class="p-2">{{ m.source or '' }}</td>
          <td class="p-2">{{ m.note or '' }}</td>
          <td class="p-2 text-right">
            <form method="post" action="{{ url_for('delete_member', member_id=m.id) }}"
                  onsubmit="return confirm('정말 삭제할까요?');">
              <button class="px-3 py-1 rounded bg-red-600 hover:bg-red-700 text-white">삭제</button>
            </form>
          </td>
        </tr>
        {% else %}
        <tr><td class="p-4 text-center text-gray-500" colspan="11">데이터가 없습니다.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
{% endblock %}
"""

app.jinja_loader = DictLoader({
    'base.html': BASE_HTML,
    'index.html': INDEX_HTML,
})

# -----------------
# 쿼리 필터 적용
# -----------------
from sqlalchemy import and_, or_

def apply_filters(query):
    q = (request.args.get("q") or "").strip()
    mtype = (request.args.get("membership_type") or "").strip()
    expired = (request.args.get("expired") or "").strip()  # '', active, expired
    join_from = parse_date(request.args.get("join_from"))
    join_to = parse_date(request.args.get("join_to"))
    exp_from = parse_date(request.args.get("exp_from"))
    exp_to = parse_date(request.args.get("exp_to"))

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Member.name.ilike(like),
                Member.contact.ilike(like),
                Member.source.ilike(like),
                Member.note.ilike(like),
            )
        )
    if mtype:
        query = query.filter(Member.membership_type == mtype)
    if expired == "active":
        query = query.filter(or_(Member.expiry_date == None, Member.expiry_date >= date.today()))
    elif expired == "expired":
        query = query.filter(and_(Member.expiry_date != None, Member.expiry_date < date.today()))

    if join_from:
        query = query.filter(Member.join_date >= join_from)
    if join_to:
        query = query.filter(Member.join_date <= join_to)
    if exp_from:
        query = query.filter(Member.expiry_date >= exp_from)
    if exp_to:
        query = query.filter(Member.expiry_date <= exp_to)

    return query

# -----------------
# 라우트
# -----------------
@app.route('/', methods=['GET', 'POST'])
def index():
    # 등록 처리
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        contact = (request.form.get('contact') or '').strip()
        membership_type = (request.form.get('membership_type') or '').strip()
        join_date = parse_date(request.form.get('join_date'))
        # 만료일 수동 입력이 있으면 사용, 없으면 자동 계산
        expiry_input = parse_date(request.form.get('expiry_date'))
        expiry_date = expiry_input or auto_expiry(join_date, membership_type)
        source = (request.form.get('source') or '').strip()
        note = (request.form.get('note') or '').strip()

        if not name or not membership_type or not join_date:
            flash('이름, 멤버십, 가입일은 필수입니다.')
            return redirect(url_for('index'))

        m = Member(
            name=name,
            contact=contact or None,
            membership_type=membership_type,
            join_date=join_date,
            expiry_date=expiry_date,
            source=source or None,
            note=note or None,
        )
        db.session.add(m)
        db.session.commit()
        flash('등록되었습니다.')
        return redirect(url_for('index', **request.args))

    # 목록 조회 + 필터
    query = apply_filters(Member.query.order_by(Member.id.desc()))
    members = query.all()
    return render_template_string(INDEX_HTML, members=members, today=date.today())

@app.post('/delete/<int:member_id>')
def delete_member(member_id: int):
    m = Member.query.get_or_404(member_id)
    db.session.delete(m)
    db.session.commit()
    flash('삭제되었습니다.')
    return redirect(url_for('index', **request.args))

@app.get('/export.csv')
def export_csv():
    query = apply_filters(Member.query.order_by(Member.id.asc()))
    rows = query.all()
    data = io.StringIO()
    writer = csv.writer(data)
    writer.writerow(["id","name","contact","membership_type","join_date","expiry_date","source","note","created_at","updated_at"])
    for m in rows:
        writer.writerow([
            m.id,
            m.name,
            m.contact or '',
            m.membership_type or '',
            m.join_date.isoformat() if m.join_date else '',
            m.expiry_date.isoformat() if m.expiry_date else '',
            m.source or '',
            (m.note or '').replace('\\n',' '),
            m.created_at.isoformat(timespec='seconds') if m.created_at else '',
            m.updated_at.isoformat(timespec='seconds') if m.updated_at else '',
        ])
    data.seek(0)
    return send_file(io.BytesIO(data.read().encode('utf-8-sig')), mimetype='text/csv; charset=utf-8', as_attachment=True, download_name='members.csv')

# -----------------
# 시작
# -----------------
if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
