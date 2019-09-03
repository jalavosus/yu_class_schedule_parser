import re
import copy
import json
import arrow
import MySQLdb
import requests
import warnings

from pprint import pprint
from bs4 import BeautifulSoup
from arrow.factory import ArrowParseWarning
from prerequisite_parser import get_prerequisite_classes

# fuckin' arrow
warnings.simplefilter("ignore", ArrowParseWarning)

TERM_SELECT_URL = "https://selfserveprod.yu.edu/pls/banprd/bwckschd.p_disp_dyn_sched"
TERM_SUBJECTS_URL = "https://selfserveprod.yu.edu/pls/banprd/bwckgens.p_proc_term_date"
COURSE_SEARCH_URL = "https://selfserveprod.yu.edu/pls/banprd/bwckschd.p_get_crse_unsec"


SUBJECTS_FORM_DATA = { "p_calling_proc": "bwckschd.p_disp_dyn_sched", "p_term": "" }

DUMMY = "dummy"
DUMMY_LIST = [ DUMMY, "%" ]

COURSE_SEARCH_FORM_DATA = {"term_in": "",          "sel_subj": [ DUMMY, "" ], "sel_crse": "", 
                           "sel_day": DUMMY,       "sel_schd": DUMMY,         "sel_insm": DUMMY, "sel_camp": DUMMY_LIST,
													 "sel_sess": DUMMY_LIST, "sel_instr": DUMMY_LIST,   "sel_ptrm": DUMMY, "sel_attr": DUMMY_LIST,
													 "sel_title": "",        "sel_from_cred": "",       "sel_to_cred": "", "begin_hh": 0, "begin_mi": 0, 
													 "begin_ap": "a",        "end_hh": 0, "end_mi": 0,  "end_ap": "a",     "sel_levl": DUMMY_LIST }


def get_values_from_select(select_data):
	vals_list = [ option.get("value") for option in select_data.find_all("option") ]
	try:
		vals_list.pop(vals_list.index(""))
	except ValueError:
		pass

	return vals_list


def get_term_values():
	r = requests.post(TERM_SELECT_URL)

	soup = BeautifulSoup(r.text, "lxml")

	term_select = soup.find("select", { "id": "term_input_id" })

	vals_list = get_values_from_select(term_select)

	return vals_list


def get_subjects_for_semester(semester_val: str):
	form_data = copy.deepcopy(SUBJECTS_FORM_DATA)
	form_data["p_term"] = semester_val

	r = requests.post(TERM_SUBJECTS_URL, data=form_data)

	soup = BeautifulSoup(r.text, "lxml")
	subjects_list = soup.find("select", { "id": "subj_id" })

	vals_list = get_values_from_select(subjects_list)

	return vals_list


def get_courses(subject_name, semester):
	form_data = copy.deepcopy(COURSE_SEARCH_FORM_DATA)
	form_data["term_in"] = semester
	form_data["sel_subj"][1] = subject_name

	r = requests.post(COURSE_SEARCH_URL, data=form_data)

	soup = BeautifulSoup(r.text, "lxml")

	return soup


def parse_class_time(classtime):
	classtime = classtime.upper().strip().split(" - ")

	start_time = arrow.get(classtime[0], "h:mm A")
	end_time = arrow.get(classtime[1], "h:mm A")

	start_time = start_time.format("HH:mm")
	end_time = end_time.format("HH:mm")

	return { "start_time": start_time, "end_time": end_time }


def parse_meeting_days(days):
	days = list(days)

	day_dict = {
		"M":	"monday",
		"T":	"tuesday",
		"W":	"wednesday",
		"R":	"thursday",
		"F":	"friday",
		"U":	"sunday",
	}

	meeting_days = [ day_dict[d] for d in days ]

	return meeting_days


def parse_course_meeting_times(schedule_data_table):
	row = schedule_data_table.find_all("tr")[1]
	
	data = row.find_all("td")

	class_times = parse_class_time(data[1].text)

	meeting_days = parse_meeting_days(data[2].text)

	location = data[3].text

	course_meeting_info = {
		"class_times":	class_times,
		"meeting_days":	meeting_days,
		"location":     location,
	}

	return course_meeting_info


def parse_other_info(course_entry_text):
	credits_re = re.compile("(\d{1,2}\.\d+)\s(?=Credits)")
	campus_re = re.compile("(\w+)\s(?=Campus)")
	level_re = re.compile("(?<=Levels: )(.+)") 		# dear god this regex is a bad idea

	credits_search = credits_re.search(course_entry_text)
	if credits_search:
		credits = float(credits_search.groups(0)[0].strip())
	else:
		credits = 0.0

	campus_search = campus_re.search(course_entry_text)
	if campus_search:
		campus = campus_search.groups(0)[0].strip()
	else:
		campus = ""
	
	level_search = level_re.search(course_entry_text)
	if level_search:
		level = level_search.groups(0)[0].strip()
		level = [l.strip().lower() for l in level.split(",")]
	else:
		level = []

	other_info = {
		"credits":	credits,
		"campus":		campus,
		"level":    level,
	}

	return other_info


def cleanup_notes(notes):
	if len(notes) < 1:
		return notes

	for sep in [ "; ", " ; ", ". ", " . " ]:
		notes = notes.replace(sep, " ")
	
	# cleanup any double spaces the above code might've caused
	notes = notes.replace("  ", " ")
	notes = notes.strip()

	return notes

def parse_course(course_rows):
	course_header = course_rows[0].text.strip()
	course_header = course_header.split(" - ")
	
	course_info = {
		"course_title":		course_header[0],
		"crn":						course_header[1],
		"course_number":  course_header[2],
		"section":        course_header[3],
	}

	course_entry = course_rows[1]
	course_entry = course_entry.find("td", class_="dddefault")
	course_info["notes"] = course_entry.next.strip().replace("\n", " ")

	other_info = parse_other_info(course_entry.text)

	course_info.update(other_info)

	# Parse the meeting times for the class
	meeting_times = course_entry.find("table", class_="datadisplaytable")
	meeting_info = parse_course_meeting_times(meeting_times)

	course_info.update(meeting_info)

	prereqs, prereq_str = get_prerequisite_classes(course_info["notes"])
	course_info["notes"] = course_info["notes"].replace(prereq_str, "")
	course_info["notes"] = cleanup_notes(course_info["notes"])

	course_info["prerequisites"] = prereqs

	return course_info
	


def insert_data_into_sql(semester, courses_for_semester):
	pass


if __name__ in "__main__":
	terms = get_term_values()

	subjects = get_subjects_for_semester(terms[1])

	ids_courses = get_courses("IDS", "201909")
	course_table = ids_courses.find("table", class_="datadisplaytable")
	tbody = course_table.find("tbody")

	children = [ c for c in course_table.children if c.name == "tr" ]

	course_list = []

	for i in range(0, len(children), 2):
		course_list.append(parse_course(children[i:i+2]))

	for c in course_list:
		pprint(c)
		print("\n")