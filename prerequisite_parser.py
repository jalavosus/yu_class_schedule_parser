import re

from pprint import pprint

CLASS_NUM_RE = re.compile("([A-Z]{3,4}\s\d{3,4}\/?[A-Z]?)")

PREREQ_RE = re.compile("(Pre-?req(.+)?:\s)([A-Za-z0-9\s\/\,]+)(?=[.;]?)")

NO_SUBJECT_RE = re.compile("(?<![A-Z]{3}\s)(\d{4}\/?[A-Z]?)")


def get_prerequisite_classes(course_notes):
	prereqs = []

	prereq_search = PREREQ_RE.search(course_notes)
	if prereq_search:
		prereq_line = prereq_search.groups(0)[-1]
	else:
		return prereqs, ""
	
	coursename_search = CLASS_NUM_RE.findall(prereq_line)
	named_courses = coursename_search or []
	
	unnamed_search = NO_SUBJECT_RE.findall(prereq_line)
	unnamed_courses = unnamed_search or []
	
	# ... not sure how to explain this pain
	named_indices = [ (prereq_line.index(nc), prereq_line.index(nc)+len(nc)) for nc in named_courses ]

	unnamed_indices = [ (prereq_line.index(uc), prereq_line.index(uc)+len(uc)) for uc in unnamed_courses ]

	fresh_named_courses = get_course_subjects(named_indices, unnamed_indices, prereq_line)

	# concat lists and make sure to get any duplicates out of the result
	all_prereqs = list(set(named_courses + fresh_named_courses))

	note_rm_line = "".join([prereq_search.groups()[0], prereq_line])
	
	return all_prereqs, note_rm_line


def get_course_subjects(named_indices, unnamed_indices, prereq_string):
	""" Let's play a game called 'How the fuck do I document this?'

	Finds the (lookbehind) closest course with a subject (ex. ACC 1001) to 
	the course without a subject (ex. 1002, for each un-subjected course.

	Prerequisite lists will often list prereqs as "ACC 1001 and 1002" which 
	is really annoying for people who want to parse prereqs out of a string. 
	So, I do some strange looping to give subjects to course numbers which
	lack them.
	"""
	newly_named_courses = []

	for un_index in unnamed_indices:
		closest_index = [ nc_index for nc_index in named_indices if nc_index[1] < un_index[0] ]
		if len(closest_index) > 0:
			closest_index = closest_index[-1]
			recent_name = prereq_string[closest_index[0]:closest_index[1]]
		else:
			continue
		subject = parse_out_subject(recent_name)
		fresh_course = f"{subject} {prereq_string[un_index[0]:un_index[1]]}"

		newly_named_courses.append(fresh_course)
	
	return newly_named_courses


def parse_out_subject(course_name):
	return course_name.split(" ")[0]
		
		
		