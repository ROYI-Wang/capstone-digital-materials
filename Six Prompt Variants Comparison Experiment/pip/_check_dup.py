import os
d = 'E:/1研究生/岭南大学/论文毕业/capstone/资料/作者们的文集'

def check(f_main, f_subs):
    main = open(os.path.join(d,f_main),'r',encoding='utf-8').read()
    print(f'=== {f_main} ({len(main)//1024}KB) ===')
    for sub in f_subs:
        s = open(os.path.join(d,sub),'r',encoding='utf-8').read()
        head = s[:80].strip()
        overlap = head in main
        # check 50-char sliding windows
        windows = sum(1 for i in range(0,len(s)-50,50) if s[i:i+50] in main)
        coverage = windows / ((len(s)-50)//50 + 1) * 100 if len(s)>50 else 0
        print(f'  {sub} ({len(s)//1024}KB): start in main={overlap}, coverage={coverage:.0f}%')

check('张君劢.txt', ['张君劢 (2).txt', '张君劢3.txt'])
check('丁文江.txt', ['丁文江2.txt', '丁文江3.txt'])
