clear
datename=$(date +%Y%m%d-%H%M%S)
train_log=('genetic_iters_20_'$datename)
mkdir log
python3 search.py --max_iters=20 --net_cache='../training/models/checkpoint.pth.tar' --data=/mnt/local0/imagenet_dataset | tee log/$train_log.search.log

python search.py --max_iters=20 --net_cache='../training/models/checkpoint.pth.tar' --data=/home/sathul/Python/ImageNet2012 --load_dict=$false | tee search.txt

python search_v2.py --max_iters=20 --net_cache='../training/models/checkpoint.pth.tar' --data=/home/sathul/Python/ImageNet2012

python search_v2.py --max_iters=20 --net_cache='../training/models/checkpoint.pth.tar' --data=/home/sathul/Python/ImageNet2012 | tee search_V2R2.txt

python search_v3.py --max_iters=20 --net_cache='../training/models/checkpoint.pth.tar' --data=/home/sathul/Python/ImageNet2012 | tee search_V3R1.txt
