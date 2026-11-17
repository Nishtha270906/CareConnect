from datetime import date, datetime
from io import BytesIO
from flask import request, make_response, flash, redirect, url_for


def register_pdf_routes(app, get_db, login_required):
    """Register a PDF report endpoint using the application's existing SQLite DB."""

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    )
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.charts.barcharts import VerticalBarChart

    @app.route('/reports/summary.pdf')
    @login_required
    def reports_pdf():

        today = date.today()
        default_start = today.replace(day=1).isoformat()
        start_date = request.args.get('start_date', default_start)
        end_date = request.args.get('end_date', today.isoformat())

        try:
            start_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_obj = datetime.strptime(end_date, '%Y-%m-%d').date()

            if start_obj > end_obj:
                raise ValueError('Start date is after end date')

        except ValueError:
            flash(
                'Please select a valid date range before exporting the PDF.',
                'warning'
            )
            return redirect(url_for('reports'))

        db = get_db()

        totals = db.execute('''
            SELECT
                COUNT(*) total,
                SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) present,
                SUM(CASE WHEN status='Absent' THEN 1 ELSE 0 END) absent,
                SUM(CASE WHEN status='Leave' THEN 1 ELSE 0 END) leave_count
            FROM attendance
            WHERE attendance_date BETWEEN ? AND ?
        ''', (start_date, end_date)).fetchone()

        present = totals['present'] or 0
        absent = totals['absent'] or 0
        leave_count = totals['leave_count'] or 0

        decided = present + absent
        rate = round(present * 100 / decided, 1) if decided else 0

        children_count = db.execute(
            "SELECT COUNT(*) FROM children WHERE status='Active'"
        ).fetchone()[0]

        activities_count = db.execute('''
            SELECT COUNT(*) FROM activities
            WHERE activity_date BETWEEN ? AND ?
        ''', (start_date, end_date)).fetchone()[0]

        sessions_count = db.execute('''
            SELECT COUNT(*) FROM support_sessions
            WHERE session_date BETWEEN ? AND ?
        ''', (start_date, end_date)).fetchone()[0]

        participation_count = db.execute('''
            SELECT COUNT(*)
            FROM participation p
            JOIN activities a ON a.id=p.activity_id
            WHERE a.activity_date BETWEEN ? AND ?
        ''', (start_date, end_date)).fetchone()[0]

        daily = db.execute('''
            SELECT attendance_date,
                SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) present,
                SUM(CASE WHEN status='Absent' THEN 1 ELSE 0 END) absent,
                SUM(CASE WHEN status='Leave' THEN 1 ELSE 0 END) leave_count
            FROM attendance
            WHERE attendance_date BETWEEN ? AND ?
            GROUP BY attendance_date
            ORDER BY attendance_date
        ''', (start_date, end_date)).fetchall()

        activities = db.execute('''
            SELECT a.title, a.category, COUNT(p.id) participants
            FROM activities a
            LEFT JOIN participation p ON p.activity_id=a.id
            WHERE a.activity_date BETWEEN ? AND ?
            GROUP BY a.id
            ORDER BY a.activity_date DESC
        ''', (start_date, end_date)).fetchall()

        support = db.execute('''
            SELECT category, COUNT(*) total,
                COALESCE(SUM(duration_minutes),0) minutes
            FROM support_sessions
            WHERE session_date BETWEEN ? AND ?
            GROUP BY category
            ORDER BY total DESC
        ''', (start_date, end_date)).fetchall()

        buffer = BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=14 * mm,
            leftMargin=14 * mm,
            topMargin=14 * mm,
            bottomMargin=14 * mm,
            title='CareConnect - Reports and Analytics',
            author='CareConnect'
        )

        styles = getSampleStyleSheet()

        styles.add(ParagraphStyle(
            name='ReportTitle',
            parent=styles['Title'],
            textColor=colors.HexColor('#17434a'),
            alignment=TA_LEFT,
            fontSize=21,
            leading=25,
            spaceAfter=4
        ))

        styles.add(ParagraphStyle(
            name='Subtle',
            parent=styles['Normal'],
            textColor=colors.HexColor('#64748b'),
            fontSize=9,
            leading=12
        ))

        styles.add(ParagraphStyle(
            name='Section',
            parent=styles['Heading2'],
            textColor=colors.HexColor('#167f73'),
            fontSize=12,
            leading=15,
            spaceBefore=10,
            spaceAfter=6
        ))

        story = [
            Paragraph(
                'CareConnect | Reports &amp; Analytics',
                styles['ReportTitle']
            ),
            Paragraph(
                f'Reporting period: {start_date} to {end_date} | '
                f'Generated: {today.isoformat()}',
                styles['Subtle']
            ),
            Spacer(1, 8)
        ]

        # Summary cards
        kpi_data = [
            [
                'ACTIVE CHILDREN',
                'ATTENDANCE RATE',
                'ACTIVITIES',
                'SUPPORT SESSIONS',
                'PARTICIPATION RECORDS'
            ],
            [
                str(children_count),
                f'{rate}%',
                str(activities_count),
                str(sessions_count),
                str(participation_count)
            ]
        ]

        kpi = Table(
            kpi_data,
            colWidths=[52 * mm] * 5,
            rowHeights=[9 * mm, 15 * mm]
        )

        kpi.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#eef6f4')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#526777')),
            ('TEXTCOLOR', (0, 1), (-1, 1), colors.HexColor('#173b48')),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 7),
            ('FONTSIZE', (0, 1), (-1, 1), 17),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#d9e7e5')),
            ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.white),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5)
        ]))

        story += [
            kpi,
            Spacer(1, 5),
            Paragraph('Attendance summary', styles['Section'])
        ]

        # Attendance table
        att_data = [
            ['Attendance status', 'Records'],
            ['Present', str(present)],
            ['Absent', str(absent)],
            ['Leave', str(leave_count)],
            ['Total records', str(totals['total'] or 0)]
        ]

        att_table = Table(
            att_data,
            colWidths=[65 * mm, 35 * mm]
        )

        att_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#17434a')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dce5e8')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.white, colors.HexColor('#f6f9fa')]),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('PADDING', (0, 0), (-1, -1), 6)
        ]))

        story.append(att_table)

        # Daily attendance chart
        if daily:
            story.append(
                Paragraph('Daily attendance trend', styles['Section'])
            )

            drawing = Drawing(245 * mm, 65 * mm)

            chart = VerticalBarChart()
            chart.x = 12 * mm
            chart.y = 12 * mm
            chart.height = 45 * mm
            chart.width = 220 * mm

            chart.data = [
                [r['present'] or 0 for r in daily],
                [r['absent'] or 0 for r in daily],
                [r['leave_count'] or 0 for r in daily]
            ]

            chart.categoryAxis.categoryNames = [
                r['attendance_date'][5:] for r in daily
            ]

            chart.categoryAxis.labels.fontSize = 6
            chart.valueAxis.valueMin = 0
            chart.valueAxis.valueStep = 1

            # Correct ReportLab axis label font property
            chart.valueAxis.labels.fontSize = 7

            chart.groupSpacing = 5
            chart.barSpacing = 1

            chart.bars[0].fillColor = colors.HexColor('#239782')
            chart.bars[1].fillColor = colors.HexColor('#e49a4b')
            chart.bars[2].fillColor = colors.HexColor('#8295b5')

            drawing.add(chart)
            story.append(drawing)

            story.append(Paragraph(
                'Legend: Present (green), Absent (orange), '
                'Leave (blue-grey).',
                styles['Subtle']
            ))

        # Activity participation
        story.append(
            Paragraph('Activity participation', styles['Section'])
        )

        activity_data = [
            ['Activity', 'Category', 'Participation records']
        ]

        activity_data += [
            [
                str(r['title']),
                str(r['category']),
                str(r['participants'] or 0)
            ]
            for r in activities
        ]

        if not activities:
            activity_data.append([
                'No activities in selected period', '', ''
            ])

        at = Table(
            activity_data,
            colWidths=[110 * mm, 65 * mm, 45 * mm],
            repeatRows=1
        )

        at.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#17434a')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dce5e8')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.white, colors.HexColor('#f6f9fa')]),
            ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('PADDING', (0, 0), (-1, -1), 5)
        ]))

        story.append(at)

        # Support session categories
        story.append(
            Paragraph('Support session categories', styles['Section'])
        )

        support_data = [
            ['Category', 'Sessions', 'Total duration (minutes)']
        ]

        support_data += [
            [
                str(r['category']),
                str(r['total']),
                str(r['minutes'] or 0)
            ]
            for r in support
        ]

        if not support:
            support_data.append([
                'No support sessions in selected period', '', ''
            ])

        st = Table(
            support_data,
            colWidths=[110 * mm, 45 * mm, 65 * mm],
            repeatRows=1
        )

        st.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#17434a')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dce5e8')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.white, colors.HexColor('#f6f9fa')]),
            ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('PADDING', (0, 0), (-1, -1), 5)
        ]))

        story.append(st)

        story += [
            Spacer(1, 10),
            Paragraph(
                'Academic prototype report. Use authorized records only. '
                'Demonstration datasets should be identified as synthetic.',
                styles['Subtle']
            )
        ]

        # Footer
        def footer(canvas, document):
            canvas.saveState()
            canvas.setFont('Helvetica', 8)
            canvas.setFillColor(colors.HexColor('#7b8794'))
            canvas.drawString(
                14 * mm,
                8 * mm,
                'CareConnect | Reports & Analytics'
            )
            canvas.drawRightString(
                landscape(A4)[0] - 14 * mm,
                8 * mm,
                f'Page {document.page}'
            )
            canvas.restoreState()

        doc.build(
            story,
            onFirstPage=footer,
            onLaterPages=footer
        )

        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = (
            f'attachment; filename=careconnect_report_'
            f'{start_date}_to_{end_date}.pdf'
        )

        return response
