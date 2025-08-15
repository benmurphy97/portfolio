from flask_wtf import FlaskForm
from wtforms import SubmitField, IntegerField
from wtforms.validators import InputRequired, NumberRange

class LeagueIDForm(FlaskForm):
    league_id = IntegerField('League ID', 
                             validators=[InputRequired(), 
                                         NumberRange(min=1, 
                                                     max=None)])
    submit = SubmitField('Generate Insights')
