from app.extensions import db


class Section(db.Model):
    """The 3 fixed blocks of the GMAT Focus Edition: QR, VR, DI."""

    __tablename__ = "sections"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(8), unique=True, nullable=False)  # 'QR', 'VR', 'DI'
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    order = db.Column(db.Integer, nullable=False, default=0)

    content_areas = db.relationship(
        "ContentArea", back_populates="section", order_by="ContentArea.order"
    )

    def __repr__(self):
        return f"<Section {self.code}>"


class ContentArea(db.Model):
    """A content/topic block within a section (e.g. Algebra within QR)."""

    __tablename__ = "content_areas"

    id = db.Column(db.Integer, primary_key=True)
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), nullable=False)
    code = db.Column(db.String(60), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    order = db.Column(db.Integer, nullable=False, default=0)

    section = db.relationship("Section", back_populates="content_areas")
    subtopics = db.relationship(
        "Subtopic", back_populates="content_area", order_by="Subtopic.order"
    )

    def __repr__(self):
        return f"<ContentArea {self.code}>"


class Subtopic(db.Model):
    """A specific skill within a content area, used for error diagnosis
    (e.g. 'Quadratic equations' within 'Algebra')."""

    __tablename__ = "subtopics"

    id = db.Column(db.Integer, primary_key=True)
    content_area_id = db.Column(db.Integer, db.ForeignKey("content_areas.id"), nullable=False)
    code = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    order = db.Column(db.Integer, nullable=False, default=0)
    # Position in the recommended study track (sample_bank/study_plan.yaml);
    # None = not on the track.
    track_order = db.Column(db.Integer, nullable=True)
    track_phase = db.Column(db.Integer, nullable=True)

    content_area = db.relationship("ContentArea", back_populates="subtopics")

    def __repr__(self):
        return f"<Subtopic {self.code}>"


class QuestionType(db.Model):
    """The rendering/answer-format template a question follows.

    codes: multiple_choice, data_sufficiency, table_analysis,
    graphics_interpretation, two_part_analysis, multi_source_reasoning
    """

    __tablename__ = "question_types"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)

    def __repr__(self):
        return f"<QuestionType {self.code}>"
