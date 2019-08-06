#!/usr/bin/python
from idaapi import *
from idautils import *
from idc import *

preclassNameToParentNameMap = {"OSObject":"", "IOService":"IORegistryEntry", "IORegistryEntry":"OSObject", "IOUserClient":"IOService", "OSDictionary":"OSObject", "OSArray": "OSObject", "OSSet": "OSObject", "IOMemoryDescriptor":"OSObject", "OSSymbol": "OSObject" }

classNameToParentNameMap = {}
classNameToVTableStructIdMap = {}
classNameToVTableEAListMap = {}
virtualFuncEASet = set()
predefinedStructNameToIdMap = {}

builtinTypeSet = set()
builtinTypeSet.add("int")
builtinTypeSet.add("unsigned int")
builtinTypeSet.add("long")
builtinTypeSet.add("unsigned long")
builtinTypeSet.add("long long")
builtinTypeSet.add("unsigned long long")
builtinTypeSet.add("float")
builtinTypeSet.add("double")
builtinTypeSet.add("char")
builtinTypeSet.add("unsigned char")
builtinTypeSet.add("bool")
builtinTypeSet.add("void")
builtinTypeSet.add("task")

def log(message):
    print message

def parseDemangledFuncNameToGetClassNameAndArglist(demangledFuncName, isVirtual):
    arglist = []
    demangledClassName = None
    if demangledFuncName != None:
        demangledFuncNameWithoutArgs = demangledFuncName[:demangledFuncName.find("(")]
        demangledClassName = demangledFuncNameWithoutArgs[:demangledFuncNameWithoutArgs.rfind("::")]
        
        if demangledFuncName.find("(") < demangledFuncName.rfind(")"):
            arglist.extend(demangledFuncName[demangledFuncName.find("(")+1:demangledFuncName.rfind(")")].split(","))
            for i in range(0, len(arglist)):
                arg = arglist[i]
                arg = arg.strip()
                if arg.endswith("*"):
                    ptrType = arg[:arg.find("*")].strip()
                    if not (ptrType in builtinTypeSet or ptrType in preclassNameToParentNameMap or ptrType in predefinedStructNameToIdMap):
                        if ptrType.endswith(" const"):
                            ptrType = ptrType[:-len(" const")]
                            if ptrType in classNameToParentNameMap:
                                arglist[i] = ptrType + " const " + arg[arg.find("*"):]
                            else:
                                arglist[i] = "void const " + arg[arg.find("*"):]
                        else:
                            if ptrType in classNameToParentNameMap:
                                arglist[i] = ptrType + arg[arg.find("*"):]
                            else:
                                arglist[i] = "void " + arg[arg.find("*"):]
        for i in range(0, len(arglist)):
            arg = arglist[i]
            if arg.strip() == "":
                arglist.pop(i)


        if len(arglist) == 1 and arglist[0] == "void":
            arglist = []

        if demangledClassName != None and (len(arglist) == 0 or arglist[0] != demangledClassName + "*"):
            arglist.insert(0, demangledClassName + " *" + "this")

    return demangledClassName, arglist

def getFuncTypeByArgList(arglist):
    funcType = "__int64 ("
    if len(arglist) == 0 :
        funcType = funcType + "void"
    elif len(arglist) == 1:
        funcType = funcType + arglist[0]
    else:
        funcType = funcType + arglist[0]
        for i in range(1, len(arglist)):
            funcType = funcType + ", " + arglist[i]
    funcType = funcType + ")"
    return funcType

def parseVTable(vtableStartEA, demangledClassName):
    alreadyExist = False
    vtableEAList = []

    vtableEndEA = vtableStartEA

    vtableStrucName = "vtable_" + demangledClassName
    classStrucName = demangledClassName

    vtableStrucId = GetStrucIdByName(vtableStrucName)
    if vtableStrucId == BADADDR:
        vtableStrucId = AddStrucEx(-1, vtableStrucName, 0)

    set_struc_hidden(get_struc(vtableStrucId), 1)

    classStrucId = GetStrucIdByName(classStrucName)
    if classStrucId == BADADDR:
        classStrucId = AddStrucEx(-1, classStrucName, 0)
        set_struc_hidden(get_struc(classStrucId), 1)
    if GetStrucSize(classStrucId) == 0:
        AddStrucMember(classStrucId, "vtable", 0, qwrdflag(), -1, 8)
    else:
        SetMemberType(classStrucId, 0, qwrdflag(), -1, 1)
        SetMemberName(classStrucId, 0, "vtable")
        
    vtableStructSize = GetStrucSize(vtableStrucId)
    if vtableStructSize > 0:
        alreadyExist = True

    ret = SetType(GetMemberId(classStrucId, 0), "struct " + vtableStrucName + " *")

    classNameToVTableStructIdMap[demangledClassName] = vtableStrucId

    while True:
        if Qword(vtableEndEA) == 0:
            vtableEndEA = vtableEndEA - 0x8   
            break
        funcEA = Qword(vtableEndEA)
        funcName = Name(funcEA) 
        funcFlags = GetFlags(funcEA)
        funcType = GetType(funcEA)
        demangledFuncName = Demangle(funcName, GetLongPrm(INF_LONG_DN))
        memberOffset = vtableEndEA-vtableStartEA

        vtableEAList.append(funcEA)
        virtualFuncEASet.add(funcEA)

        if not alreadyExist:
            # in case two members have the same name, e.g., ___cxa_pure_virtual
            AddStrucMember(vtableStrucId, "member" + str(memberOffset/8), memberOffset, qwrdflag(), -1, 8)
            SetMemberName(vtableStrucId, memberOffset, funcName)
        SetMemberComment(vtableStrucId, memberOffset, hex(funcEA), 1)
        memberId = GetMemberId(vtableStrucId, memberOffset)
        add_dref(memberId, funcEA, 1)
        add_dref(funcEA, memberId, 1)
        if funcType == None:
            funcType = GuessType(funcEA)
            if funcType == None:
                nouse, arglist = parseDemangledFuncNameToGetClassNameAndArglist(demangledFuncName, True)            
                funcType = getFuncTypeByArgList(arglist)
                if demangledFuncName != None:
                    log("Parse Type: " + demangledFuncName)
            
        if funcType != None:
            funcTypeArgStartLoc = funcType.find("(")
            funcPTRType = funcType[:funcTypeArgStartLoc] + "(*)" +  funcType[funcTypeArgStartLoc:]
            SetType(memberId, funcPTRType)

        if GetType(memberId) == None:
            if demangledFuncName != None:
                log("SetType Failed: " + demangledFuncName + " " + funcType)
            else:
                log("SetType Failed: " + funcName + " " + funcType)

        vtableEndEA = vtableEndEA + 0x8 

    classNameToVTableEAListMap[demangledClassName] = vtableEAList

def parseVTables():
    names = Names()
    for nameTuple in names:
        ea = nameTuple[0]
        name = nameTuple[1]
        demangledName = Demangle(nameTuple[1], INF_SHORT_DN)
        if demangledName != None and demangledName.startswith("`vtable for'"):
            demangledClassName = demangledName[len("`vtable for'"):]
            segName = get_segm_name(ea)
            if (segName == "__const" or segName == "__data" or segName == "__constdata"): 
                vtableStartEA = ea + 16
                parseVTable(vtableStartEA, demangledClassName)


def backwardResolve(heads, ind, reg):
    if ind < len(heads) and ind >= 0:
        i = ind-1
        while i >= 0:
            insnEA = heads[i]
            opertor = GetMnem(insnEA)
            opnd0 = GetOpnd(insnEA, 0)
            opnd1 = GetOpnd(insnEA, 1)
            if opertor == "mov":
                if opnd0 == reg:
                    opnd1Value = GetOperandValue(insnEA, 1)
                    if opnd1Value <= 0x20:
                        return backwardResolve(heads, i, opnd1)
                        None
                    else:
                        return opnd1Value
    
            elif opertor == "lea" and opnd0 == reg:
                opnd1Value = GetOperandValue(insnEA, 1)
                return opnd1Value
            i -= 1
    return None

def createClassStruct(className, classSize):
    #print "Create Class %s of Size %d"%(className, classSize)
    classStrucName = className
    classStrucId = GetStrucIdByName(classStrucName)
    if classStrucId == BADADDR:
        classStrucId = AddStrucEx(-1, classStrucName, 0)
    currentClassSize = GetStrucSize(classStrucId)
    setMemberThresholdForClassSize = 0x1300
    classSizeWithIndivMembers = classSize if classSize <= setMemberThresholdForClassSize else setMemberThresholdForClassSize
    # Add member one by one
    #print currentClassSize, classSizeWithIndivMembers
    for memberOffset in range(currentClassSize, classSizeWithIndivMembers, 8):
        AddStrucMember(classStrucId, "member" + str(memberOffset/8), memberOffset, qwrdflag(), -1, 8)
    if classSize > classSizeWithIndivMembers:
        AddStrucMember(classStrucId, "members", classSizeWithIndivMembers, qwrdflag(), -1, classSize - classSizeWithIndivMembers)
    set_struc_hidden(get_struc(classStrucId), 1)
    return classStrucId

def parseModInitFuncSeg():
    modInitFuncSegSelector = SegByName("__DATA_CONST:__mod_init_func")
    modInitFuncSegEA = SegByBase(modInitFuncSegSelector)
    modInitFuncSegStartEA = SegStart(modInitFuncSegEA)
    modInitFuncSegEndEA = SegEnd(modInitFuncSegEA)
    currentEA = modInitFuncSegStartEA
    while currentEA < modInitFuncSegEndEA:
        modInitFuncEA = Qword(currentEA)
        modInitFuncName = Name(modInitFuncEA)
        className = None
        classSize = 0
        classParentMetaClass = None
        classParentClass = None

        print "modInitFuncName: " + str(modInitFuncName)
        for (startea, endea) in Chunks(modInitFuncEA):
            heads = list(Heads(startea, endea))
            for i in range(0, len(heads)):
                insnEA = heads[i]
                opnd0 = GetOpnd(insnEA, 0)
                opertor = GetMnem(insnEA)
                if opertor == "call" and (opnd0 == "__ZN11OSMetaClassC2EPKcPKS_j" or opnd0 == "OSMetaClass::OSMetaClass(char const*,OSMetaClass const*,uint)"):
                    value = backwardResolve(heads, i, "rsi")
                    if value != None:
                        className = GetString(value)
                    value = backwardResolve(heads, i, "ecx")
                    if value != None:
                        classSize = value 
                    value = backwardResolve(heads, i, "rdx")
                    if value != None:
                        valueName = Name(value)
                        if valueName == None or valueName.startswith("off_"):
                            classParentMetaClass =  Demangle(Name(Qword(value)), GetLongPrm(INF_SHORT_DN))
                            classParentClass = classParentMetaClass[:classParentMetaClass.rfind("::")]
                        else:
                            classParentMetaClass =  Demangle(valueName, GetLongPrm(INF_SHORT_DN))
                            classParentClass = classParentMetaClass[:classParentMetaClass.rfind("::")]
                    print className, classParentClass, classSize

                    # Add class struct or fulfill existing class struct
                    classNameToParentNameMap[className] = classParentClass
                    classStrucName = className
                    createClassStruct(classStrucName, classSize)

        currentEA += 0x8

def processAllFuncArgs():
    processVirtualFuncArgsThroughVTables()
    processNonVirtualFuncArgs()

def processFuncArgs(funcEA, isVirtual, className):
    funcName = Name(funcEA)
    demangledFuncName = Demangle(funcName, GetLongPrm(INF_LONG_DN))
    classNameInFuncName, arglist = parseDemangledFuncNameToGetClassNameAndArglist(demangledFuncName, isVirtual)            
    if (isVirtual and classNameInFuncName == className) or ( (not isVirtual) and classNameInFuncName != None ):
        print "Parsing Args For Func " + funcName
        funcType = getFuncTypeByArgList(arglist)
        funcTypeArgStartLoc = funcType.find("(")
        demangledFuncNameWithoutArgs = demangledFuncName[:demangledFuncName.find("(")].strip()
        demangledFuncNameWithoutArgs = demangledFuncNameWithoutArgs.replace(":", "_")
        demangledFuncNameWithoutArgs = demangledFuncNameWithoutArgs.replace("~", "_")
        funcTypeToSet = funcType[:funcTypeArgStartLoc] + demangledFuncNameWithoutArgs +  funcType[funcTypeArgStartLoc:]
        setTypeRet = SetType(funcEA, funcTypeToSet)
        if not setTypeRet:
            log("SetType Failed: " + funcName + " " + funcTypeToSet)
            
def processVirtualFuncArgsThroughVTables():
    for className in classNameToVTableEAListMap:
        vtableEAList = classNameToVTableEAListMap[className]
        for funcEA in vtableEAList:
            processFuncArgs(funcEA, True, className)

def processNonVirtualFuncArgs():
    for ea in Segments():
        textSegEA = ea
        if SegName(ea).endswith("__text"):
            print("Found __text seg: "+str(hex(SegStart(textSegEA))))
            textSegStartEA = SegStart(textSegEA)
            textSegEndEA = SegEnd(textSegEA)
            for funcStartEA in Functions(textSegStartEA, textSegEndEA):
                if funcStartEA not in virtualFuncEASet:
                    processFuncArgs(funcStartEA, False, None)

def hideAllStructs():
    for structTuple in Structs():
        set_struc_hidden(get_struc(structTuple[1]), 1)

def preparePredefinedStructNameToIdMap():
    for idx, sid, name in Structs():
        predefinedStructNameToIdMap[name] = sid
    
def parseGOTNames():
    for ea in Segments():
        gotSegEA = ea
        if SegName(ea).endswith("__got"):
            print("Found __got seg: "+str(hex(SegStart(gotSegEA))))
            gotSegStartEA = SegStart(gotSegEA)
            gotSegEndEA = SegEnd(gotSegEA)
            currentEA = gotSegEA
            while currentEA < gotSegEndEA:
                realName = Name(Qword(currentEA))
                newName = realName + "_0"
                set_name(currentEA, newName)
                if realName.startswith("__ZTV"): # vtable
                    demangledRealName = Demangle(realName, GetLongPrm(INF_LONG_DN))
                    className = demangledRealName[len("`vtable for'"):]
                    SetType(currentEA, "struct vtable_" + className + "*")
                currentEA += 0x8

def main():
    parseGOTNames()
    preparePredefinedStructNameToIdMap()
    print "[+] Parse ModInitFunc Segments"
    parseModInitFuncSeg()
    print "[+] Parse VTables"
    parseVTables()
    print "[+] Process All Function Args"
    processAllFuncArgs()
    hideAllStructs()

if __name__ == "__main__":
    main()
