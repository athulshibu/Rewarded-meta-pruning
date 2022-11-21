clear
datename=$(date +%Y%m%d-%H%M%S)
train_log=('genetic_iters_20_'$datename)
mkdir log
python search.py --max_iters=20 --net_cache='./training/models/checkpoint.pth.tar' --data='./ImageNet2012' | tee search.txt
