/*
 * Copyright © 2011 Gerd Kohlberger
 *
 * Onboard is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3 of the License, or
 * (at your option) any later version.
 *
 * Onboard is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program. If not, see <http://www.gnu.org/licenses/>.
 */

#ifndef __OSK_MODULE__
#define __OSK_MODULE__

#include <Python.h>

/**
 * Get the module exception object.
 */
PyObject * __osk_exception_get_object (void);

#define OSK_EXCEPTION (__osk_exception_get_object ())

/**
 * Register a new python type.
 */
#define OSK_REGISTER_TYPE(__TypeName, __type_name, __PyName) \
\
static PyObject * __type_name##_new (PyTypeObject *type, PyObject *args, PyObject *kwds); \
static int __type_name##_init (__TypeName *self, PyObject *args, PyObject *kwds); \
static void __type_name##_dealloc (__TypeName *self); \
\
static PyMethodDef __type_name##_methods[]; \
\
static PyTypeObject __type_name##_type = { \
    PyObject_HEAD_INIT (NULL) \
    0,                                        /* ob_size */ \
    "osk." __PyName,                          /* tp_name */ \
    sizeof (__TypeName),                      /* tp_basicsize */ \
    0,                                        /* tp_itemsize */ \
    (destructor) __type_name##_dealloc,       /* tp_dealloc */ \
    0,                                        /* tp_print */ \
    0,                                        /* tp_getattr */ \
    0,                                        /* tp_setattr */ \
    0,                                        /* tp_compare */ \
    0,                                        /* tp_repr */ \
    0,                                        /* tp_as_number */ \
    0,                                        /* tp_as_sequence */ \
    0,                                        /* tp_as_mapping */ \
    0,                                        /* tp_hash */ \
    0,                                        /* tp_call */ \
    0,                                        /* tp_str */ \
    0,                                        /* tp_getattro */ \
    0,                                        /* tp_setattro */ \
    0,                                        /* tp_as_buffer */ \
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE, /* tp_flags */ \
    __PyName " objects",                      /* tp_doc */ \
    0,                                        /* tp_traverse */ \
    0,                                        /* tp_clear */ \
    0,                                        /* tp_richcompare */ \
    0,                                        /* tp_weaklistoffset */ \
    0,                                        /* tp_iter */ \
    0,                                        /* tp_iternext */ \
    __type_name##_methods,                    /* tp_methods */ \
    0,                                        /* tp_members */ \
    0,                                        /* tp_getset */ \
    0,                                        /* tp_base */ \
    0,                                        /* tp_dict */ \
    0,                                        /* tp_descr_get */ \
    0,                                        /* tp_descr_set */ \
    0,                                        /* tp_dictoffset */ \
    (initproc) __type_name##_init,            /* tp_init */ \
    0,                                        /* tp_alloc */ \
    __type_name##_new,                        /* tp_new */ \
}; \
\
int \
__##__type_name##_register_type (PyObject *module) \
{ \
    if (PyType_Ready (&__type_name##_type) < 0) \
        return -1;\
\
    Py_INCREF (&__type_name##_type); \
\
    if (PyModule_AddObject (module, __PyName, \
                            (PyObject *) &__type_name##_type) < 0) \
        return -1; \
\
    return 0; \
}

/**
 * Sugar for the dealloc vfunc of Python objects.
 */
#define OSK_FINISH_DEALLOC(o) ((o)->ob_type->tp_free ((PyObject *) (o)))

#endif /* __OSK_MODULE__ */
