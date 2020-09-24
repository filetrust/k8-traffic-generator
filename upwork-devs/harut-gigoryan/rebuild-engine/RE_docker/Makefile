image-name="ggrig/k8-traffic:re"

build:
	docker build -t $(image-name) .

run:
	docker run -d $(image-name)

tag:
	docker tag ggrig/k8-traffic ggrig/k8-traffic:re

push:
	docker push ggrig/k8-traffic:re
