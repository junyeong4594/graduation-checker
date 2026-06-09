
from flask import Flask, request, render_template_string
import mysql.connector
import os
import re

app = Flask(__name__)

# Railway MySQL 연결
# Railway에서 MySQL을 추가하면 MYSQLHOST, MYSQLUSER, MYSQLPASSWORD, MYSQLDATABASE, MYSQLPORT 값을 사용
def get_conn():
    return mysql.connector.connect(
        host=os.environ.get("MYSQLHOST"),
        user=os.environ.get("MYSQLUSER"),
        password=os.environ.get("MYSQLPASSWORD"),
        database=os.environ.get("MYSQLDATABASE"),
        port=int(os.environ.get("MYSQLPORT", 3306)),
        charset="utf8mb4"
    )


def run_sql_file(filename):
    conn = get_conn()
    cur = conn.cursor()

    with open(filename, "r", encoding="utf-8") as f:
        sql = f.read()

    # 주석 제거
    sql = re.sub(r"--.*", "", sql)

    statements = [s.strip() for s in sql.split(";") if s.strip()]

    for stmt in statements:
        cur.execute(stmt)

    conn.commit()
    cur.close()
    conn.close()


@app.route("/init-db")
def init_db():
    """
    최초 1회만 접속:
    https://너의주소.up.railway.app/init-db

    DB 초기화 후에는 발표 때 이 주소를 누르지 않아도 됨.
    """
    try:
        run_sql_file("graduation_deploy.sql")
        return """
        <h2>DB 초기화 완료 ✅</h2>
        <p>이제 메인 페이지로 이동해서 학번을 조회하세요.</p>
        <p><a href="/">메인으로 가기</a></p>
        """
    except Exception as e:
        return f"""
        <h2>DB 초기화 중 오류 발생 ❌</h2>
        <pre>{e}</pre>
        """


JUDGE_Q = """SELECT
    s.student_id AS 학번,
    s.student_name AS 이름,
    d1.dept_name AS 제1전공,
    CASE s.major_track
        WHEN 'intensive' THEN '심화전공'
        WHEN 'double' THEN '이중전공'
    END AS 트랙,
    d2.dept_name AS 제2전공,

    (SELECT COUNT(*)
       FROM required_course rc
      WHERE rc.curr_id = s.curr_id) AS 제1전공_전필_총개수,

    (SELECT COUNT(*)
       FROM required_course rc
       JOIN enrollment e
         ON e.course_id = rc.course_id
        AND e.student_id = s.student_id
        AND e.grade <> 'F'
      WHERE rc.curr_id = s.curr_id) AS 제1전공_전필_이수,

    (SELECT COALESCE(SUM(co.credit), 0)
       FROM enrollment e
       JOIN course co ON co.course_id = e.course_id
      WHERE e.student_id = s.student_id
        AND e.grade <> 'F'
        AND co.dept_id = c1.dept_id
        AND co.course_type = 'major_elective') AS 제1전공_전선_이수학점,

    CASE s.major_track
        WHEN 'intensive' THEN c1.elective_intensive
        WHEN 'double' THEN c1.elective_normal
    END AS 제1전공_전선_필요학점,

    (SELECT COUNT(*)
       FROM required_course rc
      WHERE rc.curr_id = s.double_curr_id) AS 제2전공_전필_총개수,

    (SELECT COUNT(*)
       FROM required_course rc
       JOIN enrollment e
         ON e.course_id = rc.course_id
        AND e.student_id = s.student_id
        AND e.grade <> 'F'
      WHERE rc.curr_id = s.double_curr_id) AS 제2전공_전필_이수,

    (SELECT COALESCE(SUM(co.credit), 0)
       FROM enrollment e
       JOIN course co ON co.course_id = e.course_id
      WHERE e.student_id = s.student_id
        AND e.grade <> 'F'
        AND co.dept_id = c2.dept_id
        AND co.course_type = 'major_elective') AS 제2전공_전선_이수학점,

    c2.elective_double AS 제2전공_전선_필요학점,

    -- 경영교과: 제1전공이 산업경영공학부일 때만 요구
    CASE WHEN c1.dept_id = 1 THEN
        (SELECT COALESCE(SUM(co.credit), 0)
           FROM enrollment e
           JOIN course co ON co.course_id = e.course_id
           JOIN elective_group_course egc ON egc.course_id = co.course_id
           JOIN elective_group eg ON eg.group_id = egc.group_id
          WHERE e.student_id = s.student_id
            AND e.grade <> 'F'
            AND eg.curr_id = s.curr_id)
    ELSE 0 END AS 경영교과_이수학점,

    CASE WHEN c1.dept_id = 1 THEN
        (SELECT COALESCE(SUM(eg.required_credit), 0)
           FROM elective_group eg
          WHERE eg.curr_id = s.curr_id)
    ELSE 0 END AS 경영교과_필요학점,

    s.human_rights_count AS 인권교육_횟수,
    4 AS 인권교육_필요,

    (SELECT COALESCE(MAX(score), 0)
       FROM certification ct
      WHERE ct.student_id = s.student_id
        AND ct.cert_type = 'TOEIC') AS 토익_점수,

    GREATEST(c1.toeic_min, COALESCE(c2.toeic_min, 0)) AS 토익_기준,

    CASE WHEN
        -- 제1전공 전필 충족
        (SELECT COUNT(*)
           FROM required_course rc
          WHERE rc.curr_id = s.curr_id)
        =
        (SELECT COUNT(*)
           FROM required_course rc
           JOIN enrollment e
             ON e.course_id = rc.course_id
            AND e.student_id = s.student_id
            AND e.grade <> 'F'
          WHERE rc.curr_id = s.curr_id)

        -- 제1전공 전선 충족
        AND
        (SELECT COALESCE(SUM(co.credit), 0)
           FROM enrollment e
           JOIN course co ON co.course_id = e.course_id
          WHERE e.student_id = s.student_id
            AND e.grade <> 'F'
            AND co.dept_id = c1.dept_id
            AND co.course_type = 'major_elective')
        >=
        (CASE s.major_track
            WHEN 'intensive' THEN c1.elective_intensive
            WHEN 'double' THEN c1.elective_normal
         END)

        -- 이중전공이면 제2전공 충족
        AND
        (
            s.double_curr_id IS NULL
            OR
            (
                (SELECT COUNT(*)
                   FROM required_course rc
                  WHERE rc.curr_id = s.double_curr_id)
                =
                (SELECT COUNT(*)
                   FROM required_course rc
                   JOIN enrollment e
                     ON e.course_id = rc.course_id
                    AND e.student_id = s.student_id
                    AND e.grade <> 'F'
                  WHERE rc.curr_id = s.double_curr_id)

                AND

                (SELECT COALESCE(SUM(co.credit), 0)
                   FROM enrollment e
                   JOIN course co ON co.course_id = e.course_id
                  WHERE e.student_id = s.student_id
                    AND e.grade <> 'F'
                    AND co.dept_id = c2.dept_id
                    AND co.course_type = 'major_elective')
                >= c2.elective_double
            )
        )

        -- 경영교과: 제1전공이 산업경영공학부일 때만 체크
        AND
        (
            c1.dept_id <> 1
            OR
            (
                (SELECT COALESCE(SUM(co.credit), 0)
                   FROM enrollment e
                   JOIN course co ON co.course_id = e.course_id
                   JOIN elective_group_course egc ON egc.course_id = co.course_id
                   JOIN elective_group eg ON eg.group_id = egc.group_id
                  WHERE e.student_id = s.student_id
                    AND e.grade <> 'F'
                    AND eg.curr_id = s.curr_id)
                >=
                (SELECT COALESCE(SUM(eg.required_credit), 0)
                   FROM elective_group eg
                  WHERE eg.curr_id = s.curr_id)
            )
        )

        -- 인권교육
        AND s.human_rights_count >= 4

        -- 어학
        AND
        (SELECT COALESCE(MAX(score), 0)
           FROM certification ct
          WHERE ct.student_id = s.student_id
            AND ct.cert_type = 'TOEIC')
        >= GREATEST(c1.toeic_min, COALESCE(c2.toeic_min, 0))

    THEN 'O' ELSE 'X' END AS 졸업가능여부

FROM student s
JOIN curriculum c1 ON c1.curr_id = s.curr_id
JOIN department d1 ON d1.dept_id = c1.dept_id
LEFT JOIN curriculum c2 ON c2.curr_id = s.double_curr_id
LEFT JOIN department d2 ON d2.dept_id = c2.dept_id
WHERE s.student_id = %(sid)s
"""


REQ_LIST_Q = """SELECT
    co.course_code,
    co.course_name,
    CASE WHEN e.enroll_id IS NULL THEN 'X' ELSE 'O' END
FROM student s
JOIN required_course rc ON rc.curr_id = %(curr)s
JOIN course co ON co.course_id = rc.course_id
LEFT JOIN enrollment e
       ON e.student_id = s.student_id
      AND e.course_id = co.course_id
      AND e.grade <> 'F'
WHERE s.student_id = %(sid)s
ORDER BY co.course_code
"""


ELEC_LIST_Q = """SELECT
    co.course_code,
    co.course_name,
    co.credit
FROM student s
JOIN curriculum cc ON cc.curr_id = %(curr)s
JOIN enrollment e
     ON e.student_id = s.student_id
    AND e.grade <> 'F'
JOIN course co ON co.course_id = e.course_id
WHERE s.student_id = %(sid)s
  AND co.dept_id = cc.dept_id
  AND co.course_type = 'major_elective'
ORDER BY co.course_code
"""


HTML = """
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>졸업요건 확인 시스템</title>
<style>
    body {
        font-family: 'Malgun Gothic', Arial, sans-serif;
        max-width: 900px;
        margin: 40px auto;
        padding: 0 20px;
        color: #222;
        background: #f7f7fb;
    }
    h1 {
        color: #3b3a8c;
        margin-bottom: 8px;
    }
    .subtitle {
        color: #666;
        margin-bottom: 24px;
    }
    .search {
        display: flex;
        gap: 8px;
        margin: 20px 0;
    }
    input {
        flex: 1;
        padding: 12px;
        font-size: 16px;
        border: 1px solid #ccc;
        border-radius: 8px;
    }
    button {
        padding: 12px 24px;
        font-size: 16px;
        background: #4a47a3;
        color: #fff;
        border: 0;
        border-radius: 8px;
        cursor: pointer;
    }
    button:hover {
        background: #38358c;
    }
    .box {
        border: 1px solid #e0e0e8;
        border-radius: 12px;
        padding: 18px 22px;
        margin: 16px 0;
        background: #fff;
        box-shadow: 0 2px 8px rgba(0,0,0,0.03);
    }
    .box h3 {
        margin: 0 0 12px;
        color: #4a47a3;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        background: #fff;
    }
    td, th {
        padding: 8px 10px;
        text-align: left;
        border-bottom: 1px solid #eee;
    }
    th {
        background: #fafaff;
    }
    .o {
        color: #1a7f37;
        font-weight: bold;
    }
    .x {
        color: #cf222e;
        font-weight: bold;
    }
    .verdict {
        font-size: 30px;
        text-align: center;
        padding: 24px;
        border-radius: 12px;
        margin-top: 20px;
        font-weight: bold;
    }
    .pass {
        background: #e6f4ea;
        color: #1a7f37;
    }
    .fail {
        background: #fce8e8;
        color: #cf222e;
    }
    .meta span {
        display: inline-block;
        margin-right: 22px;
        margin-bottom: 6px;
    }
    .ratio {
        font-weight: bold;
    }
    details summary {
        cursor: pointer;
        color: #4a47a3;
        margin-top: 8px;
        font-weight: bold;
    }
    .hint {
        font-size: 14px;
        color: #777;
    }
</style>
</head>
<body>

<h1>졸업요건 확인 시스템</h1>
<p class="subtitle">학번을 입력하면 전공필수, 전공선택, 기타 졸업요건 충족 여부를 확인합니다.</p>

<form class="search" method="get">
    <input name="sid" placeholder="학번 입력 예: 2021390703" value="{{sid or ''}}">
    <button>조회</button>
</form>

<p class="hint">
    예시 학번: 2021390703(박준영) / 2021170825(이지인) / 2024170922(니사) / 2023170843(엘리프) / 2025123123(홍길동)
</p>

{% if sid and not found %}
<div class="box">
    <p>해당 학번의 학생을 찾을 수 없습니다.</p>
</div>
{% endif %}

{% if found %}
<div class="box">
    <div class="meta">
        <span>학번: <b>{{d['학번']}}</b></span>
        <span>이름: <b>{{d['이름']}}</b></span>
        <span>트랙: <b>{{d['트랙']}}</b></span>
    </div>
    <div class="meta">
        <span>제1전공: <b>{{d['제1전공']}}</b></span>
        <span>제2전공: <b>{{d['제2전공'] or '해당 없음'}}</b></span>
    </div>
</div>

<div class="box">
    <h3>제1전공 전공필수 — {{d['제1전공']}}</h3>
    <table>
        <tr>
            <th>학수번호</th>
            <th>과목명</th>
            <th>수강</th>
        </tr>
        {% for r in req1 %}
        <tr>
            <td>{{r[0]}}</td>
            <td>{{r[1]}}</td>
            <td class="{{'o' if r[2]=='O' else 'x'}}">{{r[2]}}</td>
        </tr>
        {% endfor %}
    </table>

    <p>전공선택:
        <span class="ratio">{{d['제1전공_전선_이수학점']}} / {{d['제1전공_전선_필요학점']}}</span>
        학점
    </p>

    {% if elec1 %}
    <details>
        <summary>들은 전공선택 {{elec1|length}}과목 보기</summary>
        <table>
            {% for r in elec1 %}
            <tr>
                <td>{{r[0]}}</td>
                <td>{{r[1]}}</td>
                <td>{{r[2]}}학점</td>
            </tr>
            {% endfor %}
        </table>
    </details>
    {% endif %}
</div>

{% if d['제2전공'] %}
<div class="box">
    <h3>제2전공 전공필수 — {{d['제2전공']}}</h3>
    <table>
        <tr>
            <th>학수번호</th>
            <th>과목명</th>
            <th>수강</th>
        </tr>
        {% for r in req2 %}
        <tr>
            <td>{{r[0]}}</td>
            <td>{{r[1]}}</td>
            <td class="{{'o' if r[2]=='O' else 'x'}}">{{r[2]}}</td>
        </tr>
        {% endfor %}
    </table>

    <p>전공선택:
        <span class="ratio">{{d['제2전공_전선_이수학점']}} / {{d['제2전공_전선_필요학점']}}</span>
        학점
    </p>

    {% if elec2 %}
    <details>
        <summary>들은 전공선택 {{elec2|length}}과목 보기</summary>
        <table>
            {% for r in elec2 %}
            <tr>
                <td>{{r[0]}}</td>
                <td>{{r[1]}}</td>
                <td>{{r[2]}}학점</td>
            </tr>
            {% endfor %}
        </table>
    </details>
    {% endif %}
</div>
{% endif %}

<div class="box">
    <h3>기타 졸업요건</h3>
    <p>경영교과:
        <span class="ratio">{{d['경영교과_이수학점']}} / {{d['경영교과_필요학점']}}</span>
        학점
    </p>
    <p>인권과 성평등:
        <span class="ratio">{{d['인권교육_횟수']}} / 4</span>
        회
    </p>
    <p>어학 TOEIC:
        <span class="ratio">{{d['토익_점수']}} / {{d['토익_기준']}}</span>
        {% if d['토익_기준']==0 %}
        <span class="hint">어학조건 없음</span>
        {% endif %}
    </p>
</div>

<div class="verdict {{'pass' if d['졸업가능여부']=='O' else 'fail'}}">
    졸업 가능 여부:
    {{ '가능 ✅' if d['졸업가능여부']=='O' else '불가 ❌' }}
</div>
{% endif %}

</body>
</html>
"""


@app.route("/")
def index():
    sid = request.args.get("sid", "").strip()

    if not sid:
        return render_template_string(HTML, found=False, sid=None)

    try:
        conn = get_conn()
        cur = conn.cursor(dictionary=True)

        cur.execute(JUDGE_Q, {"sid": sid})
        d = cur.fetchone()

        if not d:
            cur.close()
            conn.close()
            return render_template_string(HTML, found=False, sid=sid)

        cur.execute(
            "SELECT curr_id, double_curr_id FROM student WHERE student_id=%(sid)s",
            {"sid": sid}
        )
        ids = cur.fetchone()
        c1 = ids["curr_id"]
        c2 = ids["double_curr_id"]

        cur.close()

        lc = conn.cursor()

        def run(q, p):
            lc.execute(q, p)
            return lc.fetchall()

        req1 = run(REQ_LIST_Q, {"sid": sid, "curr": c1})
        elec1 = run(ELEC_LIST_Q, {"sid": sid, "curr": c1})
        req2 = run(REQ_LIST_Q, {"sid": sid, "curr": c2}) if c2 else []
        elec2 = run(ELEC_LIST_Q, {"sid": sid, "curr": c2}) if c2 else []

        lc.close()
        conn.close()

        return render_template_string(
            HTML,
            found=True,
            sid=sid,
            d=d,
            req1=req1,
            elec1=elec1,
            req2=req2,
            elec2=elec2
        )

    except Exception as e:
        return f"""
        <h2>오류 발생</h2>
        <p>DB가 아직 초기화되지 않았거나 연결 정보가 잘못되었을 수 있습니다.</p>
        <p>처음 배포한 직후라면 <a href="/init-db">/init-db</a>에 먼저 접속하세요.</p>
        <pre>{e}</pre>
        """


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
